#!/usr/bin/env bash
set -euo pipefail

curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/linux_arm64/session-manager-plugin.rpm" \
  -o /tmp/session-manager-plugin.rpm

sudo dnf install -y /tmp/session-manager-plugin.rpm || sudo rpm -ivh /tmp/session-manager-plugin.rpm

session-manager-plugin --version
