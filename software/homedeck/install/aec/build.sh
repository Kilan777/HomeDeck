#!/usr/bin/env bash
# Build and install homedeck-aec (WebRTC AEC3 echo cancellation for the HomeDeck mics). Run on the Pi with sudo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
apt-get install -y -q libwebrtc-audio-processing-dev libasound2-dev >/dev/null
g++ -O2 -std=c++17 -o /tmp/homedeck-aec "$HERE/homedeck_aec.cc" \
    $(pkg-config --cflags --libs webrtc-audio-processing-1) -lasound -lm
install -m 755 /tmp/homedeck-aec /usr/local/bin/homedeck-aec
echo "installed /usr/local/bin/homedeck-aec"
