#!/usr/bin/env bash
# Installs Xray as a local SOCKS proxy (127.0.0.1:10808) so the updater can reach YouTube.
#
#   1. put the node values in /mnt/ssd/xray/node.env  (see deploy/bin/v2rayn_to_env.py)
#   2. run this script as root on the bot's box
#
# It downloads the Xray-core release if the binary is missing, renders config.json from the
# template (mode 600, owned by vvbot), installs and starts xray.service, and tells the updater
# to use the proxy by setting VV_PROXY in daemon.env.
set -euo pipefail

DIR=/mnt/ssd/xray
LOCAL_PORT=10808
HERE="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$DIR/node.env" ] || { echo "missing $DIR/node.env"; exit 1; }

if [ ! -x "$DIR/xray" ]; then
  for _ in 1 2 3 4 5; do
    curl -fsSL -C - -m 200 -o "$DIR/x.zip" \
      https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-arm64-v8a.zip && break
  done
  command -v unzip >/dev/null || apt-get install -y -qq unzip
  unzip -oq "$DIR/x.zip" xray geoip.dat geosite.dat -d "$DIR"
  rm -f "$DIR/x.zip"
  chmod +x "$DIR/xray"
fi

set -a; . "$DIR/node.env"; set +a
python3 - "$HERE/xray/config.template.json" "$DIR/config.json" "$LOCAL_PORT" <<'PY'
import os, sys
src, dst, port = sys.argv[1:4]
text = open(src, encoding="utf-8").read()
vals = {k: os.environ.get(k, "") for k in
        ("HOST", "PORT", "UUID", "FLOW", "SNI", "FP", "PUBKEY", "SHORTID", "SPIDERX")}
vals["LOCAL_PORT"] = port
for k, v in vals.items():
    text = text.replace(f"@{k}@", v)
open(dst, "w", encoding="utf-8").write(text)
PY
chown vvbot:vvbot "$DIR/config.json" "$DIR/node.env"
chmod 600 "$DIR/config.json" "$DIR/node.env"
"$DIR/xray" run -test -c "$DIR/config.json"

install -m 644 "$HERE/systemd/xray.service" /etc/systemd/system/xray.service
systemctl daemon-reload
systemctl enable --now xray.service

ENVF=/mnt/ssd/vvbot/daemon.env
touch "$ENVF"
grep -q '^VV_PROXY=' "$ENVF" || echo "VV_PROXY=socks5://127.0.0.1:$LOCAL_PORT" >> "$ENVF"
systemctl restart vvpipe-daemon.service
echo "xray is up on 127.0.0.1:$LOCAL_PORT; the updater will use it for YouTube"
