#!/usr/bin/env bash
# Full single-box bring-up. Two topologies, same shape:
#
#   live site   internet :443/:80 -> caddy (Let's Encrypt TLS)   -> nce-safe-sim :8080
#   workstation internet :443     -> caddy (internal CA, per-IP) -> nce-safe-sim :8080
#
# The live site is nce-safe-sim.com, whose DNS points at the standalone box.
# --workstation is for a development box (nce-git-ops workstation, #32), which
# has no DNS name of its own and is reached by its Elastic IP: no public CA will
# issue for a bare IP, so Caddy uses its own internal CA there. See
# deploy/Caddyfile.workstation for what that costs (a browser trust warning).
#
# Both containers run with --restart unless-stopped, so they come back after a
# reboot (the instance is on an EventBridge start/stop schedule to control cost;
# while it is stopped the site is simply down — by design).
#
# Idempotent: safe to re-run. For code-only updates use redeploy.sh, which
# leaves Caddy (and its issued certs) untouched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

NETWORK="nce-net"

# --workstation (#32): serve this box's own public IP over HTTPS instead of the
# live domain. NCE_ALLOW_CIDR restricts who may reach the app; it defaults to
# open here and is expected to be narrowed to the admin CIDR in practice — the
# security group is the other half of that control, not a substitute for it.
WORKSTATION=""
CADDYFILE="deploy/Caddyfile"
CADDY_PORTS=(-p 80:80 -p 443:443)
CADDY_ENV=()
if [ "${1:-}" = "--workstation" ]; then
  WORKSTATION=1
  shift
  CADDYFILE="deploy/Caddyfile.workstation"
  # No public ACME challenge to answer, so :80 is not needed and stays shut.
  CADDY_PORTS=(-p 443:443)

  # Default to the box's own public address. IMDSv2 is a token exchange, not a
  # plain GET — an unauthenticated read returns 401 on a box with the hop limit
  # AL2023 ships. Overridable for boxes behind NAT, where the address the world
  # reaches is not the one the instance can see.
  if [ -z "${NCE_SITE_ADDR:-}" ]; then
    IMDS_TOKEN="$(curl -s --max-time 3 -X PUT http://169.254.169.254/latest/api/token \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
    NCE_SITE_ADDR="$(curl -s --max-time 3 \
      -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
  fi
  [ -n "${NCE_SITE_ADDR:-}" ] || {
    echo "error: could not determine this box's public IP from IMDS." >&2
    echo "       Set it explicitly:  NCE_SITE_ADDR=<ip> $0 --workstation" >&2
    exit 1
  }
  CADDY_ENV=(-e NCE_SITE_ADDR="$NCE_SITE_ADDR"
             -e NCE_ALLOW_CIDR="${NCE_ALLOW_CIDR:-0.0.0.0/0 ::/0}")
  echo "==> workstation mode: serving https://$NCE_SITE_ADDR"
  echo "    allowed sources: ${NCE_ALLOW_CIDR:-0.0.0.0/0 ::/0}"
fi

# Ensure the shared Docker network exists (idempotent — created on first run).
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"

# 1. Build the image and (re)create the internal app container on nce-net.
"$SCRIPT_DIR/redeploy.sh"

# 2. Caddy — TLS terminator / reverse proxy on 80+443.
#    caddy_data persists issued certs across restarts (no needless re-issue).
echo "==> (Re)starting Caddy..."
docker rm -f caddy >/dev/null 2>&1 || true
docker run -d --name caddy --restart unless-stopped \
  --network "$NETWORK" \
  "${CADDY_PORTS[@]}" \
  "${CADDY_ENV[@]}" \
  -v "$PROJECT_ROOT/$CADDYFILE:/etc/caddy/Caddyfile:ro" \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:2-alpine

if [ -n "$WORKSTATION" ]; then
  cat <<EOF

==> Stack up. https://$NCE_SITE_ADDR

    The certificate is issued by Caddy's own CA, so browsers warn on first
    visit. To trust it on a client, install the root once:
      docker exec caddy cat /data/caddy/pki/authorities/local/root.crt

    Reachability also depends on the security group allowing 443 — that rule
    lives in nce-git-ops (workstation/terraform/security.tf).
EOF
else
  echo "==> Stack up. https://nce-safe-sim.com"
fi
