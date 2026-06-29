#!/usr/bin/env bash
#
# Generate a self-signed TLS certificate for serving the simulator over HTTPS
# from the command line (e.g. `--serve` on :443 on an EC2 instance).
#
# Usage:
#   scripts/gen-selfsigned-cert.sh [host_or_ip ...]
#
# Each argument is added to the certificate's Subject Alternative Name (SAN).
# Modern browsers validate the hostname/IP against the SAN, NOT the CN, so list
# every name or address clients will use to reach the box. localhost / 127.0.0.1
# are always included.
#
# Examples:
#   scripts/gen-selfsigned-cert.sh                       # localhost only
#   scripts/gen-selfsigned-cert.sh ec2-1-2-3-4.compute.amazonaws.com
#   scripts/gen-selfsigned-cert.sh 10.0.4.21 nce-safe-sim.net
#
# Output (git-ignored): certs/server.crt  certs/server.key
# Then enable TLS for --serve, e.g.:
#   SERVE_TLS=1 SERVE_TLS_CERTFILE=certs/server.crt SERVE_TLS_KEYFILE=certs/server.key \
#     python NceGitLab.py --serve
# (or set defaults.serve.tls in config.json — see README.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CERT_DIR="${CERT_DIR:-$PROJECT_ROOT/certs}"
DAYS="${CERT_DAYS:-365}"

mkdir -p "$CERT_DIR"

# Build the SAN list: always localhost + loopback, plus any args (IP vs DNS auto-detected).
san="DNS:localhost,IP:127.0.0.1"
for entry in "$@"; do
  if [[ "$entry" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    san="${san},IP:${entry}"
  else
    san="${san},DNS:${entry}"
  fi
done

openssl req -x509 -newkey rsa:2048 -nodes -days "$DAYS" \
  -keyout "$CERT_DIR/server.key" \
  -out    "$CERT_DIR/server.crt" \
  -subj   "/CN=Jamie Powers/O=SAIC/emailAddress=jamie.powers@saic.com" \
  -addext "subjectAltName=${san}"

chmod 600 "$CERT_DIR/server.key"

echo "Self-signed certificate written (valid ${DAYS} days):"
echo "  cert: $CERT_DIR/server.crt"
echo "  key : $CERT_DIR/server.key"
echo "  SAN : ${san}"
