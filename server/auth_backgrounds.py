"""Login-page background image service (epic #135).

Backing store is the repo itself: images are committed under
``media/login-backgrounds/`` alongside a ``credits.json`` manifest
(``{"filename.jpg": "U.S. Navy photo by ..."}``). An optional S3 staging
bucket can be previewed live during curation by setting
``auth.background.source`` to ``"s3-test"`` — production (``"repo"``, the
default) never touches S3.

Everything here degrades instead of raising: these endpoints back the login
page, which must always render even with no images configured.
"""

import json
import random
import time
from pathlib import Path

MEDIA_DIR = Path("media/login-backgrounds")
CREDITS_FILE = "credits.json"

_IMAGE_MEDIA_TYPES = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
}

# Cached staging-bucket listing (s3-test mode only) so a page reload doesn't
# re-issue ListObjectsV2. Presigned URLs are still generated fresh per request.
_s3_cache = {"key": None, "names": [], "expires": 0.0}
_S3_LIST_TTL = 300


def load_auth_config(gl=None, config_file="config.json"):
    """Return the ``auth`` section of config.json.

    Prefers the loaded NceGitLab instance (kept fresh by reload_config), but
    falls back to reading config.json directly: the login page is the front
    door and must work even when no GitLab client could be initialised.
    """
    auth = getattr(gl, "auth", None)
    if isinstance(auth, dict):
        return auth
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            auth = json.load(f).get("auth")
        return auth if isinstance(auth, dict) else {}
    except Exception:
        return {}


def background_settings(auth):
    """Split the auth section into (background, staging_s3) with defaults."""
    bg = auth.get("background") if isinstance(auth, dict) else None
    bg = bg if isinstance(bg, dict) else {}
    s3 = bg.get("staging_s3")
    s3 = s3 if isinstance(s3, dict) else {}
    return (
        {
            "rotation_seconds": bg.get("rotation_seconds", 15),
            "max_images":       bg.get("max_images", 8),
            "source":           bg.get("source", "repo"),
        },
        {
            "bucket":              s3.get("bucket", ""),
            "prefix":              s3.get("prefix", "login-backgrounds/"),
            "presign_ttl_seconds": s3.get("presign_ttl_seconds", 3600),
        },
    )


def _repo_images():
    """List committed background images and their credit lines."""
    if not MEDIA_DIR.is_dir():
        return []
    credits = {}
    credits_path = MEDIA_DIR / CREDITS_FILE
    if credits_path.is_file():
        try:
            loaded = json.loads(credits_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                credits = loaded
        except Exception:
            pass
    return [
        {
            "name":   p.name,
            "url":    f"/api/auth/backgrounds/{p.name}",
            "credit": credits.get(p.name, ""),
        }
        for p in sorted(MEDIA_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in _IMAGE_MEDIA_TYPES
    ]


def _staging_images(s3_cfg):
    """List the staging bucket and presign each object (s3-test mode)."""
    bucket, prefix = s3_cfg["bucket"], s3_cfg["prefix"]
    if not bucket:
        return []
    import boto3  # staging preview only — "repo" mode never imports it

    client = boto3.client("s3")
    cache_key = (bucket, prefix)
    now = time.time()
    if _s3_cache["key"] != cache_key or now >= _s3_cache["expires"]:
        names = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if Path(obj["Key"]).suffix.lower() in _IMAGE_MEDIA_TYPES:
                    names.append(obj["Key"])
        _s3_cache.update(key=cache_key, names=names, expires=now + _S3_LIST_TTL)
    return [
        {
            "name": Path(key).name,
            "url": client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=s3_cfg["presign_ttl_seconds"],
            ),
            "credit": "",
        }
        for key in _s3_cache["names"]
    ]


def list_backgrounds(gl=None, limit=None):
    """Build the ``GET /api/auth/backgrounds`` payload. Never raises.

    The list is shuffled server-side: ``images[0]`` is the random initial
    background the client paints immediately; the rest are its lazy-loaded
    rotation pool.
    """
    bg, s3_cfg = background_settings(load_auth_config(gl))
    payload = {"rotation_seconds": bg["rotation_seconds"], "fallback": True, "images": []}
    try:
        images = _staging_images(s3_cfg) if bg["source"] == "s3-test" else _repo_images()
    except Exception:
        images = []
    if not images:
        return payload
    random.shuffle(images)
    cap = bg["max_images"]
    if isinstance(limit, int) and limit > 0:
        cap = min(cap, limit)
    payload["images"] = images[:cap]
    payload["fallback"] = False
    return payload


def resolve_media_file(filename):
    """Map an image name to its path under MEDIA_DIR, or None if invalid.

    Same basename/traversal guard as ``GET /api/download/{filename}``, plus an
    image-extension allowlist so this can't serve credits.json or strays.
    """
    safe_name = Path(filename).name
    if (not safe_name or safe_name != filename
            or Path(safe_name).suffix.lower() not in _IMAGE_MEDIA_TYPES):
        return None
    media_dir = MEDIA_DIR.resolve()
    target = (media_dir / safe_name).resolve()
    if target.parent != media_dir or not target.is_file():
        return None
    return target


def media_type_for(path):
    return _IMAGE_MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")
