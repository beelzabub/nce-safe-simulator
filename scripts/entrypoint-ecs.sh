#!/bin/sh
# ECS container entrypoint — seeds config.json from SSM on first boot,
# then symlinks the EFS-persisted copy into /app before starting the server.
set -e

if [ ! -f /mnt/config/config.json ]; then
    echo "Seeding config.json from SSM parameter ${CONFIG_PARAM}..."
    python3 - <<'PYEOF'
import boto3, os, sys
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
param  = os.environ["CONFIG_PARAM"]
try:
    ssm = boto3.client("ssm", region_name=region)
    val = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    os.makedirs("/mnt/config", exist_ok=True)
    with open("/mnt/config/config.json", "w") as f:
        f.write(val)
    print(f"Config seeded from SSM ({len(val)} bytes)")
except Exception as e:
    print(f"ERROR: could not seed config from SSM: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
fi

ln -sf /mnt/config/config.json /app/config.json
exec python NceGitLab.py --serve
