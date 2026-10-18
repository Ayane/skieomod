#!/bin/bash
# Install once on the existing server; no GitHub credentials are needed there.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
install -d -m 0755 /opt/skieomod-autopublish /var/lib/skieomod-autopublish
install -m 0644 "$source_dir/github_autopublish.py" /opt/skieomod-autopublish/github_autopublish.py
install -m 0644 "$source_dir/skieomod-autopublish.service" /etc/systemd/system/skieomod-autopublish.service
install -m 0644 "$source_dir/skieomod-autopublish.timer" /etc/systemd/system/skieomod-autopublish.timer
systemctl daemon-reload
systemctl enable --now skieomod-autopublish.timer
systemctl start skieomod-autopublish.service
