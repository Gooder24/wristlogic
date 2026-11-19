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
cp systemd/* ~/.config/systemd/user/
printf '#!/bin/sh\nexec %s/.venv/bin/python %s/wristlogic.py "$@"\n' "$PWD" "$PWD" > ~/.local/bin/wristlogic
chmod +x ~/.local/bin/wristlogic
systemctl --user daemon-reload
systemctl --user enable --now wristlogic-web.service wristlogic-import.timer
.venv/bin/python wristlogic.py publish
