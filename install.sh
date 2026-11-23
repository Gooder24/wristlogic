#!/bin/sh
# Sets wristlogic up on asus. Once, as root: sudo ./install.sh root   (jmtpfs, mtools and the udev rule)
set -eu
cd "$(dirname "$0")"
if [ "${1:-}" = root ]; then
    apt-get install -y jmtpfs mtools
    install -m 644 60-garmin-wristlogic.rules /etc/udev/rules.d/
    udevadm control --reload
    udevadm trigger --subsystem-match=usb --attr-match=idVendor=091e
    exit 0
fi
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
mkdir -p ~/.config/systemd/user ~/.local/bin
# The web service listens on this machine's Tailscale address, or on localhost without Tailscale.
bind=$(tailscale ip -4 2>/dev/null | head -n1) || true
[ -n "$bind" ] || bind=127.0.0.1
for f in systemd/*; do sed "s/@BIND@/$bind/" "$f" > ~/.config/systemd/user/"${f#systemd/}"; done
printf '#!/bin/sh\nexec %s/.venv/bin/python %s/wristlogic.py "$@"\n' "$PWD" "$PWD" > ~/.local/bin/wristlogic
chmod +x ~/.local/bin/wristlogic
systemctl --user daemon-reload
systemctl --user enable --now wristlogic-web.service wristlogic-import.timer
.venv/bin/python wristlogic.py publish
