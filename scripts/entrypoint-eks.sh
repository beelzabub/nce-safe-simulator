#!/bin/sh
# EKS container entrypoint — syncs config.json from the SSM SecureString to the
# EFS-persisted copy on every boot (SSM is the source of truth; update it with
# `make seed-config`), then symlinks it into /app before starting the server.
set -e

echo "Syncing config.json from SSM parameter ${CONFIG_PARAM}..."
python3 - <<'PYEOF'
import boto3, os, sys
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
param  = os.environ["CONFIG_PARAM"]
dest   = "/mnt/config/config.json"
try:
    ssm = boto3.client("ssm", region_name=region)
    val = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    os.makedirs("/mnt/config", exist_ok=True)
    current = None
    if os.path.exists(dest):
        with open(dest) as f:
            current = f.read()
    if val != current:
        with open(dest, "w") as f:
            f.write(val)
        print(f"Config synced from SSM ({len(val)} bytes)")
    else:
        print("Config already matches SSM; no change")
except Exception as e:
    # Tolerate a transient SSM failure if we already have a persisted copy,
    # but fail hard if there is nothing to fall back to.
    if os.path.exists(dest):
        print(f"WARNING: could not refresh config from SSM ({e}); using existing EFS copy", file=sys.stderr)
    else:
        print(f"ERROR: could not seed config from SSM and no EFS copy exists: {e}", file=sys.stderr)
        sys.exit(1)
PYEOF

ln -sf /mnt/config/config.json /app/config.json
exec python NceGitLab.py --serve
