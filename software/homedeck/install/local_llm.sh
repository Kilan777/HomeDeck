#!/usr/bin/env bash
# Installs Ollama on the CM4 (aarch64) for a fully local, key-free Jarvis. Idempotent. No curl|sh.
# RAM note: the CM4 has 4 GB; qwen2.5:1.5b (Q4) needs ~1 GB and answers a short question in a few seconds.
set -uo pipefail
MODEL="${1:-qwen2.5:1.5b}"
ok(){ echo "  OK   $*"; }; fail(){ echo "  FAIL $*"; }
if ! command -v ollama >/dev/null 2>&1; then
  echo "==> downloading Ollama (arm64)"
  sudo apt-get install -y -qq zstd >/dev/null 2>&1 || true
  # release assets are .tar.zst now (older releases were .tgz); try both
  if curl -fL --progress-bar -o /tmp/ollama-linux-arm64.tar.zst https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64.tar.zst; then
    sudo tar -C /usr/local --zstd -xf /tmp/ollama-linux-arm64.tar.zst && ok "ollama binary installed to /usr/local/bin" || fail "extract failed"
  elif curl -fL --progress-bar -o /tmp/ollama-linux-arm64.tgz https://ollama.com/download/ollama-linux-arm64.tgz; then
    sudo tar -C /usr/local -xzf /tmp/ollama-linux-arm64.tgz && ok "ollama binary installed to /usr/local/bin" || fail "extract failed"
  else
    fail "download failed (check the network)"; exit 1
  fi
else
  ok "ollama already installed ($(ollama --version 2>/dev/null | head -1))"
fi
echo "==> service"
sudo tee /etc/systemd/system/ollama.service >/dev/null <<'UNIT'
[Unit]
Description=Ollama local LLM server (HomeDeck Jarvis)
After=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=root
Restart=always
RestartSec=3
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_NUM_THREADS=2
Environment=OLLAMA_KEEP_ALIVE=5m
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now ollama.service && ok "ollama.service enabled" || fail "service failed"
for i in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && ok "API up on 127.0.0.1:11434" || { fail "API not answering"; exit 1; }
echo "==> pulling model $MODEL (about 1 GB, a few minutes)"
if ollama pull "$MODEL" >/tmp/ollama_pull.log 2>&1; then ok "model $MODEL ready"; else fail "pull failed, see /tmp/ollama_pull.log"; exit 1; fi
echo "==> smoke test"
R=$(curl -s http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in five words.\"}]}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])' 2>/dev/null)
[ -n "$R" ] && ok "model answered: $R" || fail "no answer from the model"
echo "Done. In HomeDeck Settings > Jarvis pick 'Local' and press Test."
