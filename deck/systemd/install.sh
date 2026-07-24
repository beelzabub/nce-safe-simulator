#!/usr/bin/env bash
# Install the weekly status-deck systemd timer + service on the box (issue #213).
# Run as root. Enabling the timer is the only step that changes standing behavior.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

install -m 0644 "$HERE/nce-status-deck.service" /etc/systemd/system/nce-status-deck.service
install -m 0644 "$HERE/nce-status-deck.timer"   /etc/systemd/system/nce-status-deck.timer
chmod +x "$HERE/../weekly-status-deck.sh"
systemctl daemon-reload

echo "Installed. Next scheduled run:"
systemd-analyze calendar "Fri *-*-* 15:00:00 America/Los_Angeles" | sed -n '1,3p' || true
echo
echo "Enable the weekly timer with:   systemctl enable --now nce-status-deck.timer"
echo "Run once now (validation):      systemctl start nce-status-deck.service"
echo "Watch logs:                     journalctl -u nce-status-deck.service -f"
