"""S3 static-site hosting behind CloudFront with a private bucket (issue #216).

Decision A1 (locked): **CloudFront + private bucket via Origin Access Control
(OAC)**. The bucket blocks all public access; only the CloudFront distribution
can read it — the bucket policy is scoped to the distribution ARN through the
``aws:SourceArn`` condition. We never use the raw S3 website endpoint, and the
site is served over HTTPS.

This module is the runtime path used by the durable-job engine (#214): the
``--deploy-s3 publish|destroy|status`` subcommand on ``NceGitLab.py`` shells
into :func:`run_cli`, which drives the functions here as a subprocess job that
survives browser refreshes and server restarts. A declarative CDK equivalent of
the same CloudFront+OAC shape lives at ``cdk/s3_site_stack.py`` for operators
who prefer infrastructure-as-code; both provision the identical topology.

boto3 client usage follows ``scripts/sync_login_backgrounds.py``.

Config lives in a new ``deploy.s3`` section of ``config.json``::

    "deploy": {
      "s3": {
        "bucket": "nce-safe-sim-site",   # required
        "region": "us-east-1",           # optional (default us-east-1)
        "prefix": "",                    # optional key prefix
        "distribution_comment": "..."    # optional CloudFront comment
      }
    }
"""
import json
import mimetypes
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError, NoCredentialsError

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _REPO_ROOT / "config.json"

DEFAULT_REGION = "us-east-1"

# Local build dirs → key prefix within the bucket. ``quarto-site/`` is the site
# root; interactive + data ride alongside it exactly as ``mixins/serve.py``
# serves them (``/interactive`` and ``/data``). Missing sources are skipped.
SITE_SOURCES = [
    ("quarto-site", ""),
    ("public/interactive", "interactive"),
    ("public/data", "data"),
]

# Bucket tag that records the last successful sync (point-in-time status uses
# it). put_bucket_tagging replaces the whole tag set, which is fine — this is
# the only tag the tooling writes.
LAST_SYNC_TAG = "nce-safe-sim:last-sync"

OAC_NAME = "nce-safe-sim-site-oac"
ORIGIN_ID = "nce-safe-sim-s3-origin"
DISTRIBUTION_COMMENT = "NCE SAFe Simulator static site (issue #216)"

# AWS managed cache policy: CachingOptimized.
_CACHE_POLICY_CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"

# Content types the site relies on that mimetypes may miss or get wrong across
# platforms (e.g. .wasm for the Marimo WASM notebooks, .js as text/javascript).
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".csv": "text/csv",
    ".xml": "application/xml",
}


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def _load_config(config=None) -> dict:
    """Return the config dict. Accepts a pre-parsed dict, a path, or None
    (reads the repo's ``config.json``)."""
    if isinstance(config, dict):
        return config
    path = Path(config) if config else _CONFIG_FILE
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def s3_settings(config=None) -> SimpleNamespace:
    """Resolve the ``deploy.s3`` section into a settings namespace."""
    cfg = _load_config(config)
    s3 = (cfg.get("deploy") or {}).get("s3") or {}
    prefix = s3.get("prefix") or ""
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return SimpleNamespace(
        bucket=s3.get("bucket"),
        region=s3.get("region") or DEFAULT_REGION,
        prefix=prefix,
        comment=s3.get("distribution_comment") or DISTRIBUTION_COMMENT,
    )


# ---------------------------------------------------------------------------
# clients (mirrors scripts/sync_login_backgrounds.py — boto3 imported lazily)
# ---------------------------------------------------------------------------

def _s3_client(region):
    import boto3

    return boto3.client("s3", region_name=region)


def _cloudfront_client():
    import boto3

    # CloudFront is a global service; its control-plane API lives in us-east-1.
    return boto3.client("cloudfront", region_name="us-east-1")


# ---------------------------------------------------------------------------
# bucket discovery / naming (issue #225)
# ---------------------------------------------------------------------------

def account_id():
    """The current AWS account id via STS, or ``None`` when it can't be read
    (no boto3, no credentials). Never raises."""
    try:
        import boto3
        return boto3.client("sts").get_caller_identity().get("Account")
    except Exception:
        return None


def _bucket_region(s3, name):
    """The region a bucket lives in (``LocationConstraint`` normalised), or None."""
    try:
        loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
    except Exception:
        return None
    if not loc:
        return "us-east-1"          # the API returns null/"" for us-east-1
    if loc == "EU":
        return "eu-west-1"          # legacy alias
    return loc


def list_buckets():
    """Every bucket in the account as ``[{"name", "region"}]``.

    Resilient by design (for the Deploy Options dropdown): returns ``[]`` on any
    failure — no boto3, no credentials, or a role without ``s3:ListAllMyBuckets``
    — so the dialog still renders and "Create new" still works.
    """
    try:
        import boto3
        s3 = boto3.client("s3")
        resp = s3.list_buckets()
    except Exception:
        return []
    out = []
    for b in resp.get("Buckets", []):
        name = b.get("Name")
        if name:
            out.append({"name": name, "region": _bucket_region(s3, name)})
    return out


# S3 bucket naming rules (the subset that matters here): 3–63 chars, lowercase
# letters/digits/hyphens/dots, start and end alphanumeric.
_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def validate_bucket_name(name):
    """Return ``None`` if *name* is a legal S3 bucket name, else an error string."""
    if not name or not (3 <= len(name) <= 63):
        return "bucket name must be 3–63 characters"
    if not _BUCKET_NAME_RE.match(name):
        return ("bucket name must be lowercase letters, numbers, hyphens or dots, "
                "starting and ending with a letter or number")
    if ".." in name or ".-" in name or "-." in name:
        return "bucket name cannot contain '..', '.-' or '-.'"
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", name):
        return "bucket name cannot be formatted as an IP address"
    if name.startswith("xn--") or name.endswith("-s3alias") or name.endswith("--ol-s3"):
        return "bucket name uses a reserved prefix/suffix"
    return None


def resolve_bucket_name(base, account=None):
    """Append the account id to *base* for global uniqueness: ``${base}-${account}``.

    Deterministic — the same base always yields the same name, so a re-run of
    "create new" is idempotent and status/destroy (which read the live bucket
    from CloudFront) never need it persisted. Falls back to *base* unchanged when
    the account id can't be determined."""
    acct = account or account_id()
    return f"{base}-{acct}" if acct else base


# ---------------------------------------------------------------------------
# site file enumeration + content types
# ---------------------------------------------------------------------------

def content_type_for(path) -> str:
    ext = Path(path).suffix.lower()
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "application/octet-stream"


def _iter_site_files(root=None):
    """Yield ``(rel_key, local_path)`` for every file across :data:`SITE_SOURCES`.

    ``rel_key`` is the object key relative to the configured prefix.
    """
    base = Path(root) if root else _REPO_ROOT
    for src_rel, key_prefix in SITE_SOURCES:
        src = base / src_rel
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(src).as_posix()
            yield (f"{key_prefix}/{rel}" if key_prefix else rel), p


def _list_keys(client, bucket, prefix):
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return keys


# ---------------------------------------------------------------------------
# bucket
# ---------------------------------------------------------------------------

def ensure_bucket(client, bucket, region, *, log=print) -> bool:
    """Create the bucket if missing and (idempotently) block ALL public access.

    Returns True if the bucket was created by this call. The public-access block
    is (re)applied every time so a pre-existing bucket can never be public.
    """
    try:
        client.head_bucket(Bucket=bucket)
        log(f"  bucket s3://{bucket} exists")
        created = False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
        kwargs = {"Bucket": bucket}
        if region and region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        client.create_bucket(**kwargs)
        log(f"  created bucket s3://{bucket} ({region})")
        created = True

    client.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    return created


def sync_site(client, bucket, prefix, root=None, *, log=print):
    """Upload every site file with a correct content-type, then delete any
    object under *prefix* that is no longer part of the built site.

    Returns ``(uploaded, deleted)`` counts. Raises if there is nothing to
    upload (the site has not been built).
    """
    desired = {f"{prefix}{rel}": path for rel, path in _iter_site_files(root)}
    if not desired:
        raise RuntimeError(
            "No site files found under quarto-site/, public/interactive/, or "
            "public/data/. Build the site first "
            "(python NceGitLab.py --serve → Site → build all)."
        )

    for key, path in desired.items():
        ctype = content_type_for(path)
        client.put_object(
            Bucket=bucket, Key=key, Body=path.read_bytes(), ContentType=ctype
        )
        log(f"  put {key}  ({ctype})")

    existing = set(_list_keys(client, bucket, prefix))
    stale = sorted(existing - set(desired))
    for start in range(0, len(stale), 1000):
        batch = stale[start:start + 1000]
        client.delete_objects(
            Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch]}
        )
        for k in batch:
            log(f"  del {k}  (stale)")

    return len(desired), len(stale)


def _set_last_sync(client, bucket, ts):
    client.put_bucket_tagging(
        Bucket=bucket, Tagging={"TagSet": [{"Key": LAST_SYNC_TAG, "Value": ts}]}
    )


def _get_last_sync(client, bucket):
    try:
        resp = client.get_bucket_tagging(Bucket=bucket)
    except ClientError:
        return None
    for t in resp.get("TagSet", []):
        if t["Key"] == LAST_SYNC_TAG:
            return t["Value"]
    return None


def put_bucket_policy_for_oac(client, bucket, dist_arn, *, log=print):
    """Grant the CloudFront distribution (and only it) read access."""
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowCloudFrontServicePrincipalReadOnly",
                "Effect": "Allow",
                "Principal": {"Service": "cloudfront.amazonaws.com"},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
                "Condition": {"StringEquals": {"AWS:SourceArn": dist_arn}},
            }
        ],
    }
    client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    log("  bucket policy scoped to the CloudFront distribution (OAC)")


# ---------------------------------------------------------------------------
# CloudFront + OAC
# ---------------------------------------------------------------------------

def _bucket_domain(bucket, region):
    return f"{bucket}.s3.{region}.amazonaws.com"


def ensure_oac(cf, *, log=print) -> str:
    """Return the id of the site's Origin Access Control, creating it once."""
    for item in cf.list_origin_access_controls().get(
        "OriginAccessControlList", {}
    ).get("Items", []):
        if item.get("Name") == OAC_NAME:
            return item["Id"]
    resp = cf.create_origin_access_control(
        OriginAccessControlConfig={
            "Name": OAC_NAME,
            "Description": "OAC for the NCE SAFe Simulator static site",
            "SigningProtocol": "sigv4",
            "SigningBehavior": "always",
            "OriginAccessControlOriginType": "s3",
        }
    )
    oac_id = resp["OriginAccessControl"]["Id"]
    log(f"  created Origin Access Control {oac_id}")
    return oac_id


def find_distribution(cf, bucket, region):
    """Return ``{"id","arn","domain"}`` for the distribution whose origin is our
    bucket, or None. Matching on the origin domain keeps this idempotent without
    relying on tags CloudFront's create API can't set inline."""
    target = _bucket_domain(bucket, region)
    for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
        origins = d.get("Origins", {}).get("Items", [])
        if any(o.get("DomainName") == target for o in origins):
            return {"id": d["Id"], "arn": d["ARN"], "domain": d["DomainName"]}
    return None


# Origin domain shape we always emit: ``<bucket>.s3.<region>.amazonaws.com``.
_ORIGIN_DOMAIN_RE = re.compile(r"^(?P<bucket>.+)\.s3\.(?P<region>[a-z0-9-]+)\.amazonaws\.com$")


def _parse_origin_domain(domain):
    """Recover ``(bucket, region)`` from an S3 origin domain, or ``(None, None)``."""
    m = _ORIGIN_DOMAIN_RE.match(domain or "")
    if m:
        return m.group("bucket"), m.group("region")
    return None, None


def find_our_distribution(cf):
    """Find *this app's* distribution without knowing the bucket, by matching the
    fixed origin id (``ORIGIN_ID``) we stamp on every distribution we create.

    Returns ``{"id","arn","domain","bucket","region","status"}`` (bucket/region
    parsed from the origin domain; ``status`` is CloudFront's ``"Deployed"`` /
    ``"InProgress"``) or ``None``. This makes CloudFront the source of truth for
    the live deployment: status and destroy locate the bucket from here rather
    than from config, so a fixed/absent config value can't hide a live site.
    """
    for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
        for o in d.get("Origins", {}).get("Items", []):
            if o.get("Id") == ORIGIN_ID:
                bucket, region = _parse_origin_domain(o.get("DomainName"))
                return {
                    "id": d["Id"],
                    "arn": d["ARN"],
                    "domain": d["DomainName"],
                    "bucket": bucket,
                    "region": region,
                    "status": d.get("Status"),
                }
    return None


def _distribution_config(bucket, region, oac_id, comment):
    return {
        "CallerReference": f"nce-safe-sim-{bucket}-{int(time.time())}",
        "Comment": comment,
        "Enabled": True,
        "DefaultRootObject": "index.html",
        "Origins": {
            "Quantity": 1,
            "Items": [
                {
                    "Id": ORIGIN_ID,
                    "DomainName": _bucket_domain(bucket, region),
                    "OriginPath": "",
                    "OriginAccessControlId": oac_id,
                    # OAC replaces the legacy OAI; the identity must be empty.
                    "S3OriginConfig": {"OriginAccessIdentity": ""},
                    "CustomHeaders": {"Quantity": 0},
                }
            ],
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": ORIGIN_ID,
            "ViewerProtocolPolicy": "redirect-to-https",
            "Compress": True,
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "CachePolicyId": _CACHE_POLICY_CACHING_OPTIMIZED,
        },
        "PriceClass": "PriceClass_100",
    }


def ensure_distribution(cf, bucket, region, oac_id, comment, *, log=print):
    found = find_distribution(cf, bucket, region)
    if found:
        log(f"  distribution {found['id']} exists ({found['domain']})")
        return found
    resp = cf.create_distribution(
        DistributionConfig=_distribution_config(bucket, region, oac_id, comment)
    )
    dist = resp["Distribution"]
    info = {"id": dist["Id"], "arn": dist["ARN"], "domain": dist["DomainName"]}
    log(f"  created distribution {info['id']} ({info['domain']})")
    return info


def _disable_and_delete_distribution(cf, dist_id, *, log=print):
    cfg = cf.get_distribution_config(Id=dist_id)
    etag = cfg["ETag"]
    dc = cfg["DistributionConfig"]
    if dc.get("Enabled"):
        dc["Enabled"] = False
        etag = cf.update_distribution(
            Id=dist_id, DistributionConfig=dc, IfMatch=etag
        )["ETag"]
        log(f"  disabled distribution {dist_id}; waiting for it to deploy...")
        try:
            cf.get_waiter("distribution_deployed").wait(Id=dist_id)
        except Exception as exc:  # waiter timeout is non-fatal; delete will retry
            log(f"  waiter note: {exc}")
        etag = cf.get_distribution_config(Id=dist_id)["ETag"]
    cf.delete_distribution(Id=dist_id, IfMatch=etag)
    log(f"  deleted distribution {dist_id}")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def publish(config=None, *, root=None, log=print, bucket=None) -> dict:
    """Ensure the bucket, sync the built site, and put it behind CloudFront/OAC.

    *bucket* (issue #225) is the publish target chosen in the UI — an existing
    bucket or a freshly-named ``${base}-${account}``; it overrides the
    ``deploy.s3.bucket`` config value. Reports the HTTPS site URL. Safe to re-run:
    the bucket, OAC, and distribution are reused if they already exist.
    """
    st = s3_settings(config)
    target = bucket or st.bucket
    if not target:
        raise RuntimeError("config.json deploy.s3.bucket is not set")

    s3 = _s3_client(st.region)
    log(f"S3 publish -> s3://{target}/{st.prefix} ({st.region})")
    ensure_bucket(s3, target, st.region, log=log)
    uploaded, deleted = sync_site(s3, target, st.prefix, root=root, log=log)

    cf = _cloudfront_client()
    oac_id = ensure_oac(cf, log=log)
    dist = ensure_distribution(cf, target, st.region, oac_id, st.comment, log=log)
    put_bucket_policy_for_oac(s3, target, dist["arn"], log=log)

    ts = datetime.now(timezone.utc).isoformat()
    _set_last_sync(s3, target, ts)

    url = f"https://{dist['domain']}"
    log(f"\nPublished {uploaded} object(s), removed {deleted} stale.")
    log(f"Site URL: {url}")
    return {
        "url": url,
        "object_count": uploaded,
        "deleted": deleted,
        "distribution_id": dist["id"],
        "last_sync": ts,
        "bucket": target,
    }


def destroy(config=None, *, log=print) -> dict:
    """Tear the deployment down: disable+delete the distribution, empty the
    bucket, then delete the bucket.

    The bucket is discovered from the live CloudFront distribution (the source of
    truth), so teardown always hits what's actually deployed. Only when there is
    no distribution — a bucket created before its distribution — does this fall
    back to the configured target.
    """
    cf = _cloudfront_client()
    dist = find_our_distribution(cf)

    if dist and dist.get("bucket"):
        bucket = dist["bucket"]
        region = dist["region"] or DEFAULT_REGION
        log(f"  discovered live bucket s3://{bucket} from CloudFront")
        _disable_and_delete_distribution(cf, dist["id"], log=log)
    else:
        st = s3_settings(config)
        if not st.bucket:
            raise RuntimeError(
                "no deployed CloudFront distribution found and "
                "config.json deploy.s3.bucket is not set"
            )
        bucket, region = st.bucket, st.region
        log("  no CloudFront distribution found; using the configured bucket")

    s3 = _s3_client(region)
    keys = _list_keys(s3, bucket, "")
    for start in range(0, len(keys), 1000):
        batch = keys[start:start + 1000]
        s3.delete_objects(
            Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch]}
        )
    log(f"  emptied {len(keys)} object(s) from s3://{bucket}")

    try:
        s3.delete_bucket(Bucket=bucket)
        log(f"  deleted bucket s3://{bucket}")
    except ClientError as exc:
        log(f"  bucket not deleted: {exc}")

    return {
        "deleted_objects": len(keys),
        "distribution_id": dist["id"] if dist else None,
        "bucket": bucket,
    }


def s3_deploy_status(config=None) -> dict:
    """Point-in-time status of the S3/CloudFront deployment (issue #216).

    Standalone by design: sibling issue #215 owns ``GET /api/deploy/status`` and
    wires this in after both merge. Never touches that endpoint.

    Returns::

        {
          "state": "not_deployed" | "deploying" | "deployed" | "error",
          "url": <str|None>,
          "object_count": <int>,
          "last_sync": <iso str|None>,
        }

    CloudFront is the source of truth: if our distribution exists, the live
    ``bucket`` is derived from its origin and reported as ``deployed`` — no config
    value required. Only when there is no distribution does this fall back to the
    configured target to distinguish ``deploying`` (bucket created, distribution
    not yet) from ``not_deployed``.

    A newly created distribution is ``InProgress`` for ~15 min while CloudFront
    propagates it to the edge; during that window the URL doesn't serve yet, so it
    is reported as ``deploying`` (not ``deployed``) — the UI must not present it as
    live and ready until CloudFront reports ``Deployed``.

    States: ``not_deployed``, ``deploying`` (bucket present but distribution not
    yet live — either not created, or created and still propagating),
    ``deployed`` (distribution live), ``error`` (any AWS failure — a ``detail``
    key carries the message). ``bucket`` names the resolved bucket when known.
    """
    # 1. CloudFront first — the deployed distribution names its own bucket.
    try:
        cf = _cloudfront_client()
        dist = find_our_distribution(cf)
    except Exception:
        dist = None

    if dist and dist.get("bucket"):
        bucket = dist["bucket"]
        region = dist["region"] or DEFAULT_REGION
        object_count, last_sync = 0, None
        try:
            s3 = _s3_client(region)
            object_count = len(_list_keys(s3, bucket, ""))
            last_sync = _get_last_sync(s3, bucket)
        except Exception:
            pass

        # The distribution exists but CloudFront may still be propagating it to
        # the edge (Status="InProgress"); the URL won't resolve/serve yet, so
        # don't claim "deployed" — report "deploying" with no live URL until
        # CloudFront reports "Deployed". A missing status (older API/mocks) is
        # treated as live for backward compatibility.
        status = dist.get("status")
        if status and status != "Deployed":
            return {
                "state": "deploying",
                "url": None,
                "object_count": object_count,
                "last_sync": last_sync,
                "bucket": bucket,
                "detail": "CloudFront distribution is still propagating (can take ~15 min).",
            }
        return {
            "state": "deployed",
            "url": f"https://{dist['domain']}",
            "object_count": object_count,
            "last_sync": last_sync,
            "bucket": bucket,
        }

    # 2. No distribution — fall back to the configured target to tell
    #    "deploying" (bucket exists) from "not_deployed".
    try:
        st = s3_settings(config)
    except Exception as exc:
        return _status_error(exc)

    if not st.bucket:
        return {"state": "not_deployed", "url": None, "object_count": 0, "last_sync": None, "bucket": None}

    try:
        s3 = _s3_client(st.region)
        try:
            s3.head_bucket(Bucket=st.bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchBucket", "NotFound"):
                return {"state": "not_deployed", "url": None, "object_count": 0, "last_sync": None, "bucket": None}
            raise

        return {
            "state": "deploying",
            "url": None,
            "object_count": len(_list_keys(s3, st.bucket, st.prefix)),
            "last_sync": _get_last_sync(s3, st.bucket),
            "bucket": st.bucket,
        }
    except Exception as exc:
        return _status_error(exc)


def _status_error(exc):
    return {
        "state": "error",
        "url": None,
        "object_count": 0,
        "last_sync": None,
        "detail": str(exc),
    }


# ---------------------------------------------------------------------------
# CLI entry point for the durable-job subcommand
# ---------------------------------------------------------------------------

_S3_CONFIG_HINT = (
    'Add a "deploy": {"s3": {"bucket": "your-bucket"}} section to config.json '
    "(see config.example.json), then re-seed the deployed config with "
    "`make -C cdk seed-config`."
)

_S3_CREDS_HINT = (
    "No AWS credentials were found. When deploying from the app container, mount "
    "the host's ~/.aws into it read-only (see scripts/redeploy.sh), or launch the "
    "deploy from a box that has AWS credentials."
)


def _run_deploy_op(label, op):
    """Run a deploy op, mapping operator/AWS failures to a clean, actionable
    ``SystemExit`` (issue #226) instead of a raw botocore traceback.

    The deploy runs as a durable subprocess job, so whatever reaches stderr is
    what an operator sees in the job-log window. A missing config, absent
    credentials, or a denied permission are all operator/environment errors —
    surface each as a one-line message with a fix, not a stack dump.
    """
    try:
        op()
    except RuntimeError as exc:
        raise SystemExit(f"{label}: {exc}\n{_S3_CONFIG_HINT}")
    except NoCredentialsError:
        raise SystemExit(f"{label}: no AWS credentials found.\n{_S3_CREDS_HINT}")
    except ClientError as exc:
        err = exc.response.get("Error", {})
        code = err.get("Code", "")
        msg = err.get("Message", str(exc))
        if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
            raise SystemExit(
                f"{label}: access denied ({code}) — {msg}\n"
                "The AWS identity is missing the required S3/CloudFront permissions."
            )
        raise SystemExit(f"{label}: AWS error {code}: {msg}")


def run_cli(action, config=None, bucket=None):
    """Entry point for ``NceGitLab.py --deploy-s3 ACTION``.

    ``publish`` and ``destroy`` run as durable subprocess jobs; ``status``
    prints the status JSON (handy for operators / smoke tests). *bucket* is the
    publish target chosen in the UI (issue #225), overriding config; destroy
    ignores it (the live bucket is discovered from CloudFront).

    Operator/environment errors — a missing/invalid ``deploy.s3`` config, absent
    AWS credentials, or a denied permission — exit with a clean, actionable
    message (``SystemExit``) instead of a raw traceback (issue #226); that
    message is what shows in the deploy job's log window.
    """
    if action == "publish":
        _run_deploy_op("S3 deploy", lambda: publish(config, bucket=bucket))
    elif action == "destroy":
        _run_deploy_op("S3 destroy", lambda: destroy(config))
    elif action == "status":
        print(json.dumps(s3_deploy_status(config), indent=2))
    else:
        raise SystemExit(f"Unknown deploy-s3 action: {action!r}")
