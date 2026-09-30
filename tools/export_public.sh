#!/usr/bin/env bash
# Publish a snapshot of this (private) repo to the public mirror github.com/Kilan777/HomeDeck.
# What is left out: the camera / security-clip module and the intercom (modules/camera.py, modules/intercom.py,
# web/apps/camera.js and the script tag that loads it). What is scrubbed: the owner's public hostname, home
# coordinates and address placeholder. Re-run any time; each run is one commit on the mirror.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
MIRROR="${MIRROR:-$HOME/HomeDeck-public}"
REMOTE="git@github.com:Kilan777/HomeDeck.git"
HEAD_SHA=$(git -C "$SRC" rev-parse --short HEAD)

if [[ ! -d "$MIRROR/.git" ]]; then
  git clone "$REMOTE" "$MIRROR" 2>/dev/null || { mkdir -p "$MIRROR"; git -C "$MIRROR" init -q -b main; git -C "$MIRROR" remote add origin "$REMOTE"; }
fi
# fresh tree: everything tracked at HEAD, then the exclusions
find "$MIRROR" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git -C "$SRC" archive HEAD | tar -x -C "$MIRROR"
rm -f "$MIRROR/software/homedeck/modules/camera.py" "$MIRROR/software/homedeck/modules/intercom.py" "$MIRROR/software/homedeck/web/apps/camera.js"
sed -i '/apps\/camera\.js/d' "$MIRROR/software/homedeck/web/index.html"
# scrub personal details
grep -rl --exclude-dir=.git -E "jarvis\.kilanrou\.com|37\.7662|-122\.4247|123 Main Street" "$MIRROR" | while read -r f; do
  sed -i -e 's/jarvis\.kilanrou\.com/jarvis.example.com/g' -e 's/37\.7662/37.7749/g' -e 's/-122\.4247/-122.4194/g' -e 's/123 Main Street/123 Main Street/g' "$f"
done
# note at the top of the README
python3 - "$MIRROR/README.md" "$HEAD_SHA" <<'PY'
import sys
p, sha = sys.argv[1], sys.argv[2]
s = open(p).read()
note = ("> **Public mirror.** This is a snapshot of the private working repo (commit `" + sha + "`). "
        "The camera / security-clip module and the intercom are not included; everything else is as it runs on the device.\n\n")
if "Public mirror." not in s:
    lines = s.split("\n", 1)
    s = lines[0] + "\n\n" + note + (lines[1] if len(lines) > 1 else "")
else:
    import re
    s = re.sub(r"\(commit `[0-9a-f]+`\)", "(commit `" + sha + "`)", s)
open(p, "w").write(s)
PY
cd "$MIRROR"
git add -A
if git diff --cached --quiet; then echo "mirror already up to date"; exit 0; fi
git -c user.name="$(git -C "$SRC" config user.name)" -c user.email="$(git -C "$SRC" config user.email)" commit -q -m "Snapshot of the private repo at $HEAD_SHA ($(date +%Y-%m-%d))"
git push -q -u origin main
echo "published https://github.com/Kilan777/HomeDeck at $HEAD_SHA"
