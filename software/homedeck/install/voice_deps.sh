#!/usr/bin/env bash
# HomeDeck voice dependencies for the CM4 (Pi OS Trixie, aarch64). Idempotent; re-run any time.
#   wake word: openWakeWord (onnx runtime)     STT: faster-whisper (CTranslate2, int8 on CPU)
#   LLM: anthropic SDK                         TTS: piper binary + en_US-lessac-medium voice (espeak-ng as fallback)
set -u
DATA=${HOMEDECK_DATA:-/var/lib/homedeck}
PIPER_DIR=$DATA/piper
VOICE=${PIPER_VOICE:-en_US-lessac-medium}
ok=(); bad=()
note() { echo "==> $*"; }

# ---------------------------------------------------------------- apt
note "apt packages"
sudo apt-get install -y --no-install-recommends ffmpeg espeak-ng libportaudio2 python3-pip python3-numpy >/dev/null 2>&1 \
  && ok+=("apt: ffmpeg espeak-ng libportaudio2") || bad+=("apt install failed (run: sudo apt-get install ffmpeg espeak-ng libportaudio2)")

# ---------------------------------------------------------------- pip
note "pip packages (this takes a few minutes on the CM4)"
VENV=/opt/homedeck/venv
[[ -x $VENV/bin/python ]] || python3 -m venv --system-site-packages "$VENV"
PY="$VENV/bin/python"
if "$PY" -m pip install --upgrade pip >/dev/null 2>&1; "$PY" -m pip install openwakeword onnxruntime faster-whisper anthropic >/tmp/homedeck_pip.log 2>&1; then
  ok+=("pip: openwakeword onnxruntime faster-whisper anthropic")
else
  bad+=("pip install failed, see /tmp/homedeck_pip.log")
fi

# ---------------------------------------------------------------- wake word models
note "openWakeWord models (hey_jarvis)"
if "$PY" - <<'PY' >/tmp/homedeck_oww.log 2>&1
import openwakeword
from openwakeword.utils import download_models
download_models(["hey_jarvis"])
from openwakeword.model import Model
m = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
print("loaded", list(m.models.keys()))
PY
then ok+=("openWakeWord hey_jarvis model downloaded and loads"); else bad+=("openWakeWord model download/load failed, see /tmp/homedeck_oww.log"); fi

# ---------------------------------------------------------------- whisper model warm-up (downloads base.en to the HF cache)
note "faster-whisper base.en (downloads ~75 MB on first run)"
if "$PY" -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8'); print('ok')" >/tmp/homedeck_whisper.log 2>&1
then ok+=("faster-whisper base.en cached"); else bad+=("faster-whisper model download failed, see /tmp/homedeck_whisper.log"); fi

# ---------------------------------------------------------------- piper
note "piper TTS binary + voice -> $PIPER_DIR"
sudo mkdir -p "$PIPER_DIR" && sudo chown "$(id -u):$(id -g)" "$PIPER_DIR"
if [ ! -x "$PIPER_DIR/piper/piper" ]; then
  if curl -fsSL -o /tmp/piper.tar.gz https://github.com/rhasspy/piper/releases/latest/download/piper_linux_aarch64.tar.gz \
     && tar -xzf /tmp/piper.tar.gz -C "$PIPER_DIR"; then
    ok+=("piper binary installed")
  else
    bad+=("piper binary download failed (https://github.com/rhasspy/piper/releases, piper_linux_aarch64.tar.gz)")
  fi
else
  ok+=("piper binary already present")
fi
# voice files live at huggingface.co/rhasspy/piper-voices/<lang>/<locale>/<name>/<quality>/
IFS=- read -r LOCALE NAME QUALITY <<<"$VOICE"          # en_US lessac medium
LANG_SHORT=${LOCALE%%_*}
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/$LANG_SHORT/$LOCALE/$NAME/$QUALITY"
if [ ! -s "$PIPER_DIR/$VOICE.onnx" ] || [ ! -s "$PIPER_DIR/$VOICE.onnx.json" ]; then
  if curl -fsSL -o "$PIPER_DIR/$VOICE.onnx" "$BASE/$VOICE.onnx" && curl -fsSL -o "$PIPER_DIR/$VOICE.onnx.json" "$BASE/$VOICE.onnx.json"; then
    ok+=("piper voice $VOICE downloaded")
  else
    bad+=("piper voice download failed ($BASE)")
  fi
else
  ok+=("piper voice $VOICE already present")
fi
if [ -x "$PIPER_DIR/piper/piper" ] && [ -s "$PIPER_DIR/$VOICE.onnx" ]; then
  if echo "HomeDeck voice is ready." | "$PIPER_DIR/piper/piper" --model "$PIPER_DIR/$VOICE.onnx" --output_file /tmp/homedeck_tts_test.wav >/dev/null 2>&1; then
    ok+=("piper synthesised a test wav (/tmp/homedeck_tts_test.wav)")
  else
    bad+=("piper binary runs but synthesis failed (check: $PIPER_DIR/piper/piper --help)")
  fi
fi

# ---------------------------------------------------------------- report
echo
echo "================ voice deps summary ================"
for s in "${ok[@]}";  do echo "  OK   $s"; done
for s in "${bad[@]}"; do echo "  FAIL $s"; done
echo "Restart the service to pick everything up:  sudo systemctl restart homedeck"
[ ${#bad[@]} -eq 0 ]
