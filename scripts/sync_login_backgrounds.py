#!/usr/bin/env python3
"""Curation pipeline for the login-page background images (epic #135).

The committed directory ``media/login-backgrounds/`` is the images' final
home; S3 is only an intermediate staging area so candidates can be previewed
live on the login page (config ``auth.background.source: "s3-test"``) before
being committed.

Subcommands
-----------
stage <dir>       Optimize every image in <dir> (resize to 1920 px wide,
                  re-encode as JPEG q80 — which also strips EXIF) and upload
                  to the staging bucket. Credits are read from an optional
                  <dir>/credits.json ({"filename": "U.S. Navy photo by ..."})
                  and stored as S3 object metadata.
list              List currently staged candidates.
promote [name..]  Pull staged images (all by default, or the named ones) into
                  media/login-backgrounds/ and merge their credit lines into
                  media/login-backgrounds/credits.json, ready to commit.

Bucket/prefix default from config.json's ``auth.background.staging_s3``
section (falling back to nce-safe-sim-assets / login-backgrounds/) and can be
overridden with --bucket/--prefix. All subcommands accept --dry-run.

The staging bucket is created once, out of band, with public access blocked:
    aws s3api create-bucket --bucket nce-safe-sim-assets
Operator-run tooling — not part of the deploy or server runtime.
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = REPO_ROOT / "media" / "login-backgrounds"
CREDITS_FILE = "credits.json"

DEFAULT_BUCKET = "nce-safe-sim-assets"
DEFAULT_PREFIX = "login-backgrounds/"

SOURCE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
TARGET_WIDTH = 1920
JPEG_QUALITY = 80


def staging_defaults():
    """Bucket/prefix from config.json auth.background.staging_s3, if present."""
    try:
        with open(REPO_ROOT / "config.json", "r", encoding="utf-8") as f:
            s3 = json.load(f)["auth"]["background"]["staging_s3"]
        return s3.get("bucket", DEFAULT_BUCKET), s3.get("prefix", DEFAULT_PREFIX)
    except Exception:
        return DEFAULT_BUCKET, DEFAULT_PREFIX


def slugify(stem):
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "image"


def optimize(path):
    """Return (jpeg_bytes, (w, h)) — resized to TARGET_WIDTH, EXIF dropped."""
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > TARGET_WIDTH:
            im = im.resize(
                (TARGET_WIDTH, round(im.height * TARGET_WIDTH / im.width)),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return buf.getvalue(), im.size


def load_credits(path):
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def s3_client():
    import boto3

    return boto3.client("s3")


def cmd_stage(args, bucket, prefix):
    src = Path(args.source_dir)
    images = sorted(p for p in src.iterdir() if p.suffix.lower() in SOURCE_EXTS) if src.is_dir() else []
    if not images:
        sys.exit(f"No images found in {src}")
    credits = load_credits(src / CREDITS_FILE)

    client = None if args.dry_run else s3_client()
    for p in images:
        name = f"{slugify(p.stem)}.jpg"
        key = f"{prefix}{name}"
        credit = credits.get(p.name, "") or credits.get(name, "")
        if not credit:
            print(f"WARNING: no credit line for {p.name} — add it to {src / CREDITS_FILE}", file=sys.stderr)
        data, (w, h) = optimize(p)
        print(f"{'DRY-RUN ' if args.dry_run else ''}stage {p.name} -> s3://{bucket}/{key}  ({w}x{h}, {len(data) // 1024} KB)")
        if not args.dry_run:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType="image/jpeg",
                CacheControl="max-age=86400",
                Metadata={"credit": credit} if credit else {},
            )
    print(f"{len(images)} image(s) staged. Preview live with auth.background.source=\"s3-test\".")


def staged_keys(client, bucket, prefix):
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].lower().endswith(".jpg")]
    return keys


def cmd_list(args, bucket, prefix):
    client = s3_client()
    keys = staged_keys(client, bucket, prefix)
    if not keys:
        print(f"Nothing staged under s3://{bucket}/{prefix}")
        return
    for key in keys:
        head = client.head_object(Bucket=bucket, Key=key)
        credit = head.get("Metadata", {}).get("credit", "")
        print(f"{Path(key).name:40} {head['ContentLength'] // 1024:4} KB  {credit}")


def cmd_promote(args, bucket, prefix):
    client = s3_client()
    keys = staged_keys(client, bucket, prefix)
    if args.names:
        wanted = set(args.names)
        keys = [k for k in keys if Path(k).name in wanted]
        missing = wanted - {Path(k).name for k in keys}
        if missing:
            sys.exit(f"Not staged: {', '.join(sorted(missing))}")
    if not keys:
        sys.exit(f"Nothing to promote under s3://{bucket}/{prefix}")

    credits_path = MEDIA_DIR / CREDITS_FILE
    credits = load_credits(credits_path)
    for key in keys:
        name = Path(key).name
        head = client.head_object(Bucket=bucket, Key=key)
        credit = head.get("Metadata", {}).get("credit", "")
        print(f"{'DRY-RUN ' if args.dry_run else ''}promote s3://{bucket}/{key} -> {MEDIA_DIR / name}")
        if args.dry_run:
            continue
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(MEDIA_DIR / name))
        if credit:
            credits[name] = credit
    if not args.dry_run:
        credits_path.write_text(json.dumps(credits, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{len(keys)} image(s) promoted; credits merged into {credits_path}. Review and commit.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", help="staging bucket (default: config.json auth.background.staging_s3)")
    parser.add_argument("--prefix", help="staging key prefix (default: config.json / login-backgrounds/)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stage = sub.add_parser("stage", help="optimize + upload candidate images")
    p_stage.add_argument("source_dir")
    p_stage.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="list staged candidates")

    p_promote = sub.add_parser("promote", help="pull staged images into media/login-backgrounds/")
    p_promote.add_argument("names", nargs="*", help="staged filenames (default: all)")
    p_promote.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    cfg_bucket, cfg_prefix = staging_defaults()
    bucket = args.bucket or cfg_bucket
    prefix = args.prefix or cfg_prefix
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    {"stage": cmd_stage, "list": cmd_list, "promote": cmd_promote}[args.command](args, bucket, prefix)


if __name__ == "__main__":
    main()
