"""Tests for server/deploy_s3.py — S3 static-site hosting behind CloudFront/OAC
(issue #216). All AWS access is mocked; nothing here touches real AWS."""
import json

import pytest
from botocore.exceptions import ClientError

from server import deploy_s3


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeS3:
    """In-memory stand-in for a boto3 S3 client covering the calls deploy_s3
    makes: head/create bucket, public-access block, put/list/delete objects,
    bucket policy, and bucket tagging."""

    def __init__(self, exists=False):
        self.store = {}            # key -> {"Body": bytes, "ContentType": str}
        self.exists = exists
        self.public_block = None
        self.policy = None
        self.tags = {}
        self.created = False
        self.deleted_bucket = False

    def head_bucket(self, Bucket):
        if not self.exists:
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, **kw):
        self.exists = True
        self.created = True
        self.create_kwargs = kw

    def put_public_access_block(self, Bucket, PublicAccessBlockConfiguration):
        self.public_block = PublicAccessBlockConfiguration

    def put_object(self, Bucket, Key, Body, ContentType):
        self.store[Key] = {"Body": Body, "ContentType": ContentType}

    def get_paginator(self, op):
        assert op == "list_objects_v2"
        store = self.store

        class _Pager:
            def paginate(self, Bucket, Prefix=""):
                items = [{"Key": k} for k in sorted(store) if k.startswith(Prefix)]
                return [{"Contents": items}]

        return _Pager()

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.store.pop(o["Key"], None)

    def put_bucket_policy(self, Bucket, Policy):
        self.policy = json.loads(Policy)

    def put_bucket_tagging(self, Bucket, Tagging):
        self.tags = {t["Key"]: t["Value"] for t in Tagging["TagSet"]}

    def get_bucket_tagging(self, Bucket):
        if not self.tags:
            raise ClientError({"Error": {"Code": "NoSuchTagSet"}}, "GetBucketTagging")
        return {"TagSet": [{"Key": k, "Value": v} for k, v in self.tags.items()]}

    def delete_bucket(self, Bucket):
        self.deleted_bucket = True
        self.exists = False


class FakeCloudFront:
    def __init__(self, bucket="b", region="us-east-1", with_dist=False):
        self.bucket = bucket
        self.region = region
        self.oacs = []
        self.dists = {}
        self._n = 1
        self.deleted = []
        self.disabled = []
        if with_dist:
            self._add_dist()

    def _domain(self):
        return f"{self.bucket}.s3.{self.region}.amazonaws.com"

    def _add_dist(self):
        did = f"DIST{self._n}"
        self._n += 1
        self.dists[did] = {
            "Id": did,
            "ARN": f"arn:aws:cloudfront::123456789012:distribution/{did}",
            "DomainName": f"{did.lower()}.cloudfront.net",
            # The fixed ORIGIN_ID is how find_our_distribution locates us.
            "Origins": {"Items": [{"DomainName": self._domain(), "Id": deploy_s3.ORIGIN_ID}]},
            "_config": {"Enabled": True},
        }
        return did

    # OAC ------------------------------------------------------------------
    def list_origin_access_controls(self):
        return {"OriginAccessControlList": {"Items": list(self.oacs)}}

    def create_origin_access_control(self, OriginAccessControlConfig):
        oid = f"OAC{self._n}"
        self._n += 1
        self.oacs.append({"Id": oid, "Name": OriginAccessControlConfig["Name"]})
        return {"OriginAccessControl": {"Id": oid}}

    # distributions --------------------------------------------------------
    def list_distributions(self):
        return {"DistributionList": {"Items": list(self.dists.values())}}

    def create_distribution(self, DistributionConfig):
        did = f"DIST{self._n}"
        self._n += 1
        origin = DistributionConfig["Origins"]["Items"][0]
        d = {
            "Id": did,
            "ARN": f"arn:aws:cloudfront::123456789012:distribution/{did}",
            "DomainName": f"{did.lower()}.cloudfront.net",
            "Origins": {"Items": [{"DomainName": origin["DomainName"], "Id": origin.get("Id")}]},
            "_config": DistributionConfig,
        }
        self.dists[did] = d
        return {"Distribution": d}

    def get_distribution_config(self, Id):
        return {"ETag": "ETAG", "DistributionConfig": self.dists[Id]["_config"]}

    def update_distribution(self, Id, DistributionConfig, IfMatch):
        self.dists[Id]["_config"] = DistributionConfig
        if not DistributionConfig.get("Enabled"):
            self.disabled.append(Id)
        return {"ETag": "ETAG2"}

    def get_waiter(self, name):
        from types import SimpleNamespace

        return SimpleNamespace(wait=lambda **kw: None)

    def delete_distribution(self, Id, IfMatch):
        self.deleted.append(Id)
        self.dists.pop(Id, None)


@pytest.fixture
def site_tree(tmp_path):
    """A minimal built site across the three SITE_SOURCES dirs."""
    (tmp_path / "quarto-site").mkdir()
    (tmp_path / "quarto-site" / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "quarto-site" / "app.js").write_text("console.log(1)")
    (tmp_path / "quarto-site" / "styles.css").write_text("body{}")
    (tmp_path / "public" / "interactive").mkdir(parents=True)
    (tmp_path / "public" / "interactive" / "board.wasm").write_bytes(b"\0asm")
    (tmp_path / "public" / "data").mkdir(parents=True)
    (tmp_path / "public" / "data" / "metrics.json").write_text("{}")
    return tmp_path


# ---------------------------------------------------------------------------
# content types
# ---------------------------------------------------------------------------

def test_content_type_for_known_web_types():
    assert deploy_s3.content_type_for("a.html").startswith("text/html")
    assert deploy_s3.content_type_for("a.js").startswith("text/javascript")
    assert deploy_s3.content_type_for("a.css").startswith("text/css")
    assert deploy_s3.content_type_for("a.json") == "application/json"
    assert deploy_s3.content_type_for("a.wasm") == "application/wasm"
    assert deploy_s3.content_type_for("a.svg") == "image/svg+xml"


def test_content_type_for_unknown_defaults_to_octet_stream():
    assert deploy_s3.content_type_for("a.zzz") == "application/octet-stream"


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def test_s3_settings_defaults_and_prefix_slash():
    st = deploy_s3.s3_settings({"deploy": {"s3": {"bucket": "b", "prefix": "site"}}})
    assert st.bucket == "b"
    assert st.region == "us-east-1"
    assert st.prefix == "site/"  # trailing slash added


def test_s3_settings_missing_section():
    st = deploy_s3.s3_settings({})
    assert st.bucket is None
    assert st.prefix == ""


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def test_sync_uploads_all_with_content_types(site_tree):
    s3 = FakeS3(exists=True)
    uploaded, deleted = deploy_s3.sync_site(s3, "b", "", root=site_tree, log=lambda *a: None)

    assert uploaded == 5
    assert deleted == 0
    assert s3.store["index.html"]["ContentType"].startswith("text/html")
    assert s3.store["app.js"]["ContentType"].startswith("text/javascript")
    assert s3.store["interactive/board.wasm"]["ContentType"] == "application/wasm"
    assert s3.store["data/metrics.json"]["ContentType"] == "application/json"


def test_sync_honours_prefix(site_tree):
    s3 = FakeS3(exists=True)
    deploy_s3.sync_site(s3, "b", "site/", root=site_tree, log=lambda *a: None)
    assert "site/index.html" in s3.store
    assert "site/interactive/board.wasm" in s3.store


def test_sync_deletes_stale_objects(site_tree):
    s3 = FakeS3(exists=True)
    # Pre-seed an object that is NOT part of the built site.
    s3.store["old-page.html"] = {"Body": b"x", "ContentType": "text/html"}
    s3.store["data/gone.json"] = {"Body": b"{}", "ContentType": "application/json"}

    uploaded, deleted = deploy_s3.sync_site(s3, "b", "", root=site_tree, log=lambda *a: None)

    assert deleted == 2
    assert "old-page.html" not in s3.store
    assert "data/gone.json" not in s3.store
    assert "index.html" in s3.store  # current file survives


def test_sync_stale_deletion_respects_prefix(site_tree):
    s3 = FakeS3(exists=True)
    # Object outside the prefix must NOT be deleted.
    s3.store["other/keepme.html"] = {"Body": b"x", "ContentType": "text/html"}
    s3.store["site/stale.html"] = {"Body": b"x", "ContentType": "text/html"}

    _, deleted = deploy_s3.sync_site(s3, "b", "site/", root=site_tree, log=lambda *a: None)

    assert deleted == 1
    assert "other/keepme.html" in s3.store
    assert "site/stale.html" not in s3.store


def test_sync_raises_when_nothing_built(tmp_path):
    s3 = FakeS3(exists=True)
    with pytest.raises(RuntimeError):
        deploy_s3.sync_site(s3, "b", "", root=tmp_path, log=lambda *a: None)


# ---------------------------------------------------------------------------
# bucket
# ---------------------------------------------------------------------------

def test_ensure_bucket_creates_and_blocks_public_access():
    s3 = FakeS3(exists=False)
    created = deploy_s3.ensure_bucket(s3, "b", "us-west-2", log=lambda *a: None)
    assert created is True
    assert s3.created is True
    assert s3.create_kwargs["CreateBucketConfiguration"] == {"LocationConstraint": "us-west-2"}
    assert s3.public_block == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }


def test_ensure_bucket_us_east_1_has_no_location_constraint():
    s3 = FakeS3(exists=False)
    deploy_s3.ensure_bucket(s3, "b", "us-east-1", log=lambda *a: None)
    assert "CreateBucketConfiguration" not in s3.create_kwargs


def test_ensure_bucket_idempotent_when_exists():
    s3 = FakeS3(exists=True)
    created = deploy_s3.ensure_bucket(s3, "b", "us-east-1", log=lambda *a: None)
    assert created is False
    assert s3.created is False
    # public-access block re-applied even on a pre-existing bucket
    assert s3.public_block is not None


# ---------------------------------------------------------------------------
# CloudFront / OAC
# ---------------------------------------------------------------------------

def test_ensure_oac_creates_then_reuses():
    cf = FakeCloudFront()
    first = deploy_s3.ensure_oac(cf, log=lambda *a: None)
    assert first == "OAC1"
    # second call finds the existing one by name — no new OAC
    second = deploy_s3.ensure_oac(cf, log=lambda *a: None)
    assert second == "OAC1"
    assert len(cf.oacs) == 1


def test_ensure_distribution_creates_then_finds_by_origin():
    cf = FakeCloudFront(bucket="b", region="us-east-1")
    info = deploy_s3.ensure_distribution(cf, "b", "us-east-1", "OAC1", "c", log=lambda *a: None)
    assert info["domain"].endswith(".cloudfront.net")
    # re-running matches the existing distribution by origin domain
    again = deploy_s3.ensure_distribution(cf, "b", "us-east-1", "OAC1", "c", log=lambda *a: None)
    assert again["id"] == info["id"]
    assert len(cf.dists) == 1


def test_bucket_policy_scoped_to_distribution_arn():
    s3 = FakeS3(exists=True)
    deploy_s3.put_bucket_policy_for_oac(s3, "b", "arn:aws:cloudfront::1:distribution/D", log=lambda *a: None)
    stmt = s3.policy["Statement"][0]
    assert stmt["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert stmt["Condition"]["StringEquals"]["AWS:SourceArn"] == "arn:aws:cloudfront::1:distribution/D"
    assert stmt["Resource"] == "arn:aws:s3:::b/*"


# ---------------------------------------------------------------------------
# publish (end to end, mocked clients)
# ---------------------------------------------------------------------------

def test_publish_end_to_end(site_tree, monkeypatch):
    s3 = FakeS3(exists=False)
    cf = FakeCloudFront(bucket="mybucket", region="us-east-1")
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)

    config = {"deploy": {"s3": {"bucket": "mybucket", "region": "us-east-1"}}}
    result = deploy_s3.publish(config, root=site_tree, log=lambda *a: None)

    assert result["url"].startswith("https://") and result["url"].endswith(".cloudfront.net")
    assert result["object_count"] == 5
    assert s3.created is True
    assert s3.public_block["BlockPublicPolicy"] is True
    # bucket policy scoped to the created distribution
    assert s3.policy["Statement"][0]["Condition"]["StringEquals"]["AWS:SourceArn"].startswith("arn:aws:cloudfront")
    # last-sync tag written
    assert deploy_s3.LAST_SYNC_TAG in s3.tags


def test_publish_requires_bucket():
    with pytest.raises(RuntimeError):
        deploy_s3.publish({"deploy": {"s3": {}}}, log=lambda *a: None)


def test_run_cli_publish_missing_bucket_is_clean_exit():
    # A missing bucket is operator error, not a bug: run_cli converts the
    # RuntimeError into a SystemExit with an actionable config hint (no traceback)
    # so the message reads cleanly in the deploy job's log window.
    with pytest.raises(SystemExit) as exc:
        deploy_s3.run_cli("publish", config={"deploy": {"s3": {}}})
    msg = str(exc.value)
    assert "bucket is not set" in msg
    assert "config.json" in msg and "seed-config" in msg


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

def test_destroy_empties_bucket_and_deletes_distribution(monkeypatch):
    s3 = FakeS3(exists=True)
    s3.store = {"index.html": {"Body": b"x", "ContentType": "text/html"},
                "data/m.json": {"Body": b"{}", "ContentType": "application/json"}}
    cf = FakeCloudFront(bucket="mybucket", region="us-east-1", with_dist=True)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)

    config = {"deploy": {"s3": {"bucket": "mybucket", "region": "us-east-1"}}}
    result = deploy_s3.destroy(config, log=lambda *a: None)

    assert result["deleted_objects"] == 2
    assert s3.store == {}
    assert s3.deleted_bucket is True
    assert cf.disabled == ["DIST1"]   # disabled before delete
    assert cf.deleted == ["DIST1"]


def test_destroy_without_distribution(monkeypatch):
    s3 = FakeS3(exists=True)
    cf = FakeCloudFront(bucket="mybucket", region="us-east-1", with_dist=False)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)

    result = deploy_s3.destroy({"deploy": {"s3": {"bucket": "mybucket"}}}, log=lambda *a: None)
    assert result["distribution_id"] is None
    assert s3.deleted_bucket is True


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_not_deployed_when_no_bucket_configured(monkeypatch):
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: FakeCloudFront(with_dist=False))
    st = deploy_s3.s3_deploy_status({})
    assert st["state"] == "not_deployed"
    assert st["url"] is None and st["bucket"] is None


def test_status_not_deployed_when_bucket_missing(monkeypatch):
    s3 = FakeS3(exists=False)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: FakeCloudFront())
    st = deploy_s3.s3_deploy_status({"deploy": {"s3": {"bucket": "b"}}})
    assert st["state"] == "not_deployed"
    assert st["url"] is None


def test_status_deploying_when_bucket_but_no_distribution(monkeypatch):
    s3 = FakeS3(exists=True)
    s3.store = {"index.html": {"Body": b"x", "ContentType": "text/html"}}
    cf = FakeCloudFront(bucket="b", region="us-east-1", with_dist=False)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)
    st = deploy_s3.s3_deploy_status({"deploy": {"s3": {"bucket": "b"}}})
    assert st["state"] == "deploying"
    assert st["object_count"] == 1
    assert st["url"] is None


def test_status_deployed_with_url_and_last_sync(monkeypatch):
    s3 = FakeS3(exists=True)
    s3.store = {"index.html": {"Body": b"x", "ContentType": "text/html"}}
    s3.tags = {deploy_s3.LAST_SYNC_TAG: "2026-07-09T00:00:00+00:00"}
    cf = FakeCloudFront(bucket="b", region="us-east-1", with_dist=True)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)
    st = deploy_s3.s3_deploy_status({"deploy": {"s3": {"bucket": "b", "region": "us-east-1"}}})
    assert st["state"] == "deployed"
    assert st["url"].endswith(".cloudfront.net")
    assert st["object_count"] == 1
    assert st["last_sync"] == "2026-07-09T00:00:00+00:00"


def test_status_error_is_captured(monkeypatch):
    def _boom(region):
        raise RuntimeError("aws exploded")

    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: FakeCloudFront(with_dist=False))
    monkeypatch.setattr(deploy_s3, "_s3_client", _boom)
    st = deploy_s3.s3_deploy_status({"deploy": {"s3": {"bucket": "b"}}})
    assert st["state"] == "error"
    assert "aws exploded" in st["detail"]


# --- CloudFront is the source of truth (issue #225) ------------------------

def test_status_deployed_derived_from_cloudfront_without_config(monkeypatch):
    # No bucket in config at all — status must still report deployed and name the
    # live bucket, derived from the CloudFront distribution's origin.
    s3 = FakeS3(exists=True)
    s3.store = {"index.html": {"Body": b"x", "ContentType": "text/html"}}
    cf = FakeCloudFront(bucket="live-bucket", region="us-west-2", with_dist=True)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)
    st = deploy_s3.s3_deploy_status({})   # empty config
    assert st["state"] == "deployed"
    assert st["bucket"] == "live-bucket"
    assert st["url"].endswith(".cloudfront.net")


def test_destroy_discovers_bucket_from_cloudfront_ignoring_config(monkeypatch):
    s3 = FakeS3(exists=True)
    s3.store = {"index.html": {"Body": b"x", "ContentType": "text/html"}}
    cf = FakeCloudFront(bucket="live-bucket", region="us-east-1", with_dist=True)
    monkeypatch.setattr(deploy_s3, "_s3_client", lambda region: s3)
    monkeypatch.setattr(deploy_s3, "_cloudfront_client", lambda: cf)
    # config names a *different* bucket — destroy must use the CloudFront one.
    result = deploy_s3.destroy({"deploy": {"s3": {"bucket": "stale-config-bucket"}}}, log=lambda *a: None)
    assert result["bucket"] == "live-bucket"
    assert s3.deleted_bucket is True
    assert cf.deleted == ["DIST1"]


def test_parse_origin_domain_roundtrip():
    assert deploy_s3._parse_origin_domain("my-bucket.s3.us-east-1.amazonaws.com") == ("my-bucket", "us-east-1")
    assert deploy_s3._parse_origin_domain("not-an-origin.example.com") == (None, None)


# --- bucket naming / listing (issue #225) ----------------------------------

@pytest.mark.parametrize("name", ["abc", "nce-safe-sim-site", "my.bucket-1", "a1b"])
def test_validate_bucket_name_accepts_legal(name):
    assert deploy_s3.validate_bucket_name(name) is None


@pytest.mark.parametrize("name", [
    "ab",                       # too short
    "a" * 64,                   # too long
    "MyBucket",                 # uppercase
    "under_score",              # underscore
    "-leading",                 # starts with hyphen
    "trailing-",                # ends with hyphen
    "double..dot",              # consecutive dots
    "192.168.0.1",              # IP-formatted
    "xn--punycode",             # reserved prefix
])
def test_validate_bucket_name_rejects_illegal(name):
    assert deploy_s3.validate_bucket_name(name) is not None


def test_resolve_bucket_name_appends_account(monkeypatch):
    monkeypatch.setattr(deploy_s3, "account_id", lambda: "123456789012")
    assert deploy_s3.resolve_bucket_name("nce-safe-sim-site") == "nce-safe-sim-site-123456789012"


def test_resolve_bucket_name_uses_explicit_account():
    assert deploy_s3.resolve_bucket_name("base", account="999") == "base-999"


def test_resolve_bucket_name_falls_back_without_account(monkeypatch):
    monkeypatch.setattr(deploy_s3, "account_id", lambda: None)
    assert deploy_s3.resolve_bucket_name("base") == "base"


def test_list_buckets_empty_on_failure(monkeypatch):
    import boto3
    def _boom(*a, **k):
        raise RuntimeError("no creds")
    monkeypatch.setattr(boto3, "client", _boom)
    assert deploy_s3.list_buckets() == []


def test_list_buckets_maps_names_and_regions(monkeypatch):
    import boto3

    class _FakeS3:
        def list_buckets(self):
            return {"Buckets": [{"Name": "one"}, {"Name": "two"}]}
        def get_bucket_location(self, Bucket):
            return {"LocationConstraint": None if Bucket == "one" else "us-west-2"}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3())
    buckets = deploy_s3.list_buckets()
    assert buckets == [
        {"name": "one", "region": "us-east-1"},
        {"name": "two", "region": "us-west-2"},
    ]
