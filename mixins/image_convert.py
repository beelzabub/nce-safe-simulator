"""Image Conversion tools — OVA → AMI → EC2, and back (issue #285).

Wraps AWS VM Import/Export: ``import-image`` reads an OVA straight from S3 and
registers an AMI (no intermediate file — the artifact is EBS snapshots), and
the reverse direction exports either a running/stopped instance to a true .ova
container or an AMI to a VMDK/VHD/RAW disk image, landing the file back in the
bucket. Every completed import also writes a receipt JSON next to the source
OVA so the conversion is auditable and reversible (`ova-import-cleanup` reads
it to tear everything down again).

AWS access follows server/deploy_s3.py conventions: boto3 is imported lazily,
and operator/environment failures (no credentials, missing role, denied
permission) surface as a clean one-line ``SystemExit`` — that message is what
shows in the web UI job-log window — never a raw botocore traceback.

Account prerequisites (the `vmimport` service role and the OVA bucket) are
created idempotently by ``ova-import-setup`` so the capability is reproducible
on any account, including after an enclave lift.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# The service role name is fixed by AWS: import-image assumes `vmimport` unless
# told otherwise, and keeping the default means zero extra knobs in the tools.
VMIMPORT_ROLE = "vmimport"

# Security group the launch step creates/reuses in the default VPC. SSH-only;
# imported appliances have no other known-good ports.
SSH_SG_NAME = "nce-ova-import-ssh"

# Poll cadences (seconds). Import/export tasks run 10–45 min; one status line
# per poll keeps the 1 s job tailer showing life without flooding the log.
IMPORT_POLL_SECONDS = 20
EXPORT_POLL_SECONDS = 20
INSTANCE_POLL_SECONDS = 10
# Give up waiting (the AWS task itself keeps running; the message says how to
# check on it) rather than hold a job slot forever.
IMPORT_TIMEOUT_SECONDS = 120 * 60

# Download/upload progress steps for ova-fetch.
_DOWNLOAD_CHUNK = 1 << 20            # 1 MiB read chunks
_PROGRESS_EVERY_BYTES = 64 << 20     # one progress line per 64 MiB

_CREDS_HINT = (
    "No AWS credentials were found. Configure the default provider chain "
    "(instance profile, ~/.aws, or AWS_* env vars) on the box running the job."
)


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def receipt_key(source_key):
    """S3 key of the receipt JSON written next to a source OVA."""
    return f"{source_key}.import.json"


def split_s3_key(key, bucket=None):
    """Normalise a key param that may be a full ``s3://bucket/key`` URI.

    The S3 console's "Copy S3 URI" button hands users exactly that form, so
    every key-taking tool accepts it. Returns ``(bucket, key)``: a plain key
    passes through with *bucket* unchanged; a URI's bucket is used unless an
    explicit *bucket* param was given (the explicit param wins).
    """
    if key and key.startswith("s3://"):
        rest = key[len("s3://"):]
        uri_bucket, _, uri_key = rest.partition("/")
        if not uri_key:
            raise SystemExit(
                f"'{key}' names a bucket but no object — expected "
                "s3://<bucket>/<path>/<file>.ova"
            )
        return bucket or uri_bucket, uri_key
    return bucket, key


def vmimport_trust_policy():
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "vmie.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:Externalid": VMIMPORT_ROLE}},
        }],
    }


def vmimport_role_policy(bucket):
    """Inline policy for the vmimport role, scoped to *bucket*.

    Covers both directions: read the staged OVA (import) and write the exported
    image back (export-image / instance export use the same role for S3 writes).
    """
    arn = f"arn:aws:s3:::{bucket}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetBucketLocation", "s3:GetBucketAcl", "s3:ListBucket",
                    "s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload",
                ],
                "Resource": [arn, f"{arn}/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:ModifySnapshotAttribute", "ec2:CopySnapshot",
                    "ec2:RegisterImage", "ec2:Describe*",
                ],
                "Resource": "*",
            },
        ],
    }


class ImageConvertMixin:

    # ------------------------------------------------------------------ #
    # settings / clients / error surface
    # ------------------------------------------------------------------ #

    def _ic_settings(self, bucket=None):
        """Resolved image-conversion settings (config + account id).

        The configured bucket is a BASE name; the account id is appended for
        global uniqueness (same convention as deploy_s3.resolve_bucket_name),
        so the identical config works on any account — e.g. after an enclave
        lift. An explicit *bucket* argument is used verbatim.
        """
        cfg = getattr(self, "image_conversion", {}) or {}
        region = cfg.get("region", "us-east-1")
        if not bucket:
            base = cfg.get("bucket", "nce-safe-sim-ova")
            acct = self._ic_account_id()
            bucket = f"{base}-{acct}" if acct and not base.endswith(acct) else base
        return SimpleNamespace(
            bucket=bucket,
            region=region,
            instance_type=cfg.get("instance_type", "t3.micro"),
            staging_prefix=cfg.get("staging_prefix", "staging/"),
            export_prefix=cfg.get("export_prefix", "exports/"),
            lifecycle_days=int(cfg.get("lifecycle_expire_days", 14)),
        )

    def _ic_account_id(self):
        try:
            return self._ic_client("sts").get_caller_identity().get("Account")
        except Exception:
            return None

    def _ic_client(self, service, region=None):
        import boto3
        return boto3.client(service, region_name=region)

    def _ic_run(self, label, op):
        """Run *op*, mapping AWS/operator failures to a clean SystemExit
        (server/deploy_s3._run_deploy_op conventions, issue #226)."""
        from botocore.exceptions import ClientError, NoCredentialsError
        try:
            return op()
        except NoCredentialsError:
            raise SystemExit(f"{label}: no AWS credentials found.\n{_CREDS_HINT}")
        except ClientError as exc:
            err = exc.response.get("Error", {})
            code = err.get("Code", "")
            msg = err.get("Message", str(exc))
            if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
                raise SystemExit(
                    f"{label}: access denied ({code}) — {msg}\n"
                    "The AWS identity is missing the required S3/EC2/IAM permissions."
                )
            if code in ("InvalidParameter", "InvalidParameterValue") and "vmimport" in msg:
                raise SystemExit(
                    f"{label}: {msg}\nThe '{VMIMPORT_ROLE}' service role is missing or "
                    "misconfigured — run the ova-import-setup tool first."
                )
            raise SystemExit(f"{label}: AWS error {code}: {msg}")

    # ------------------------------------------------------------------ #
    # ova-import-setup — idempotent account prerequisites
    # ------------------------------------------------------------------ #

    def _tool_ova_import_setup(self, bucket=None, lifecycle_days=None, dry_run=False):
        """Check/create the OVA bucket and the `vmimport` service role.

        Safe to re-run: existing resources are reported, missing ones created,
        and the role's inline policy is re-put each run so it converges on the
        current bucket scope.
        """
        s = self._ic_settings(bucket)
        days = int(lifecycle_days) if lifecycle_days else s.lifecycle_days
        print(f"ova-import-setup — bucket s3://{s.bucket} ({s.region}), "
              f"role '{VMIMPORT_ROLE}', staged OVAs expire after {days} days")
        self._ic_run("ova-import-setup", lambda: self._ova_import_setup(s, days, dry_run))

    def _ova_import_setup(self, s, days, dry_run):
        from botocore.exceptions import ClientError
        s3 = self._ic_client("s3", s.region)
        iam = self._ic_client("iam")

        # -- bucket ----------------------------------------------------- #
        try:
            s3.head_bucket(Bucket=s.bucket)
            bucket_exists = True
        except ClientError:
            bucket_exists = False
        if bucket_exists:
            print(f"  bucket   : exists — s3://{s.bucket}")
        elif dry_run:
            print(f"  bucket   : MISSING — would create s3://{s.bucket} (private)")
        else:
            kwargs = {"Bucket": s.bucket}
            if s.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": s.region}
            s3.create_bucket(**kwargs)
            s3.put_public_access_block(
                Bucket=s.bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True, "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
                },
            )
            print(f"  bucket   : created — s3://{s.bucket} (private)")

        if dry_run and not bucket_exists:
            print(f"  lifecycle: would expire '{s.staging_prefix}*' after {days} days")
        else:
            s3.put_bucket_lifecycle_configuration(
                Bucket=s.bucket,
                LifecycleConfiguration={"Rules": [{
                    "ID": "expire-staged-ovas",
                    "Filter": {"Prefix": s.staging_prefix},
                    "Status": "Enabled",
                    "Expiration": {"Days": days},
                }]},
            )
            print(f"  lifecycle: '{s.staging_prefix}*' expires after {days} days")

        # -- vmimport role ---------------------------------------------- #
        try:
            iam.get_role(RoleName=VMIMPORT_ROLE)
            role_exists = True
        except ClientError:
            role_exists = False
        if role_exists:
            print(f"  role     : exists — {VMIMPORT_ROLE}")
        elif dry_run:
            print(f"  role     : MISSING — would create '{VMIMPORT_ROLE}' "
                  f"(trust vmie.amazonaws.com, ExternalId={VMIMPORT_ROLE})")
        else:
            iam.create_role(
                RoleName=VMIMPORT_ROLE,
                AssumeRolePolicyDocument=json.dumps(vmimport_trust_policy()),
                Description="VM Import/Export service role (nce-safe-simulator)",
            )
            print(f"  role     : created — {VMIMPORT_ROLE}")

        if dry_run and not role_exists:
            print(f"  policy   : would attach inline policy scoped to s3://{s.bucket}")
        else:
            iam.put_role_policy(
                RoleName=VMIMPORT_ROLE,
                PolicyName="vmimport-s3-ec2",
                PolicyDocument=json.dumps(vmimport_role_policy(s.bucket)),
            )
            print(f"  policy   : inline 'vmimport-s3-ec2' converged (scoped to s3://{s.bucket})")

        print("Setup complete." if not dry_run else "Dry run — nothing was changed.")

    # ------------------------------------------------------------------ #
    # ova-fetch — stage a source OVA into the bucket
    # ------------------------------------------------------------------ #

    def _tool_ova_fetch(self, url, sha256=None, bucket=None, key=None, dry_run=False):
        """Download *url*, verify its SHA-256 when given, upload to the bucket."""
        bucket, key = split_s3_key(key, bucket)
        s = self._ic_settings(bucket)
        filename = Path(url.split("?", 1)[0].rstrip("/")).name or "image.ova"
        key = key or f"{s.staging_prefix}{filename}"
        print(f"ova-fetch — {url}")
        print(f"  target: s3://{s.bucket}/{key}")
        if dry_run:
            print(f"  sha256: {'verify ' + sha256 if sha256 else 'not checked'}")
            print("Dry run — nothing was downloaded.")
            return
        self._ic_run("ova-fetch", lambda: self._ova_fetch(s, url, sha256, key))

    def _ova_fetch(self, s, url, sha256, key):
        import hashlib
        import tempfile

        import requests

        digest = hashlib.sha256()
        tmp = Path(tempfile.mkdtemp(prefix="ova-fetch-")) / Path(key).name
        # (15, 60): connect fast-fail, generous read window — the bulk-HTTP
        # timeout convention used for report fetches.
        with requests.get(url, stream=True, timeout=(15, 60)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            next_mark = _PROGRESS_EVERY_BYTES
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        pct = f" ({done * 100 // total}%)" if total else ""
                        print(f"  downloaded {_fmt_bytes(done)}{pct}")
                        next_mark += _PROGRESS_EVERY_BYTES
        print(f"  downloaded {_fmt_bytes(done)} — done")

        actual = digest.hexdigest()
        if sha256:
            if actual.lower() != sha256.strip().lower():
                tmp.unlink(missing_ok=True)
                raise SystemExit(
                    f"ova-fetch: SHA-256 mismatch — expected {sha256}, got {actual}. "
                    "Refusing to upload a corrupt/tampered image."
                )
            print("  sha256: verified")
        else:
            print(f"  sha256: {actual} (no expected value supplied)")

        s3 = self._ic_client("s3", s.region)
        print(f"  uploading to s3://{s.bucket}/{key} …")
        s3.upload_file(str(tmp), s.bucket, key)
        head = s3.head_object(Bucket=s.bucket, Key=key)
        print(f"Staged s3://{s.bucket}/{key} ({_fmt_bytes(head['ContentLength'])}). "
              f"Next: run ova-to-ami with key={key}")
        tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # ova-to-ami — the core conversion
    # ------------------------------------------------------------------ #

    def _tool_ova_to_ami(self, key, bucket=None, name=None, launch=True,
                         instance_type=None, key_name=None, dry_run=False):
        """Import an OVA from S3 as an AMI, optionally launch it, write a receipt."""
        bucket, key = split_s3_key(key, bucket)
        s = self._ic_settings(bucket)
        name = name or f"{Path(key).stem}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
        itype = instance_type or s.instance_type
        print(f"ova-to-ami — s3://{s.bucket}/{key}")
        print(f"  AMI name     : {name}")
        print(f"  launch       : {'yes — ' + itype if launch else 'no (import only)'}")
        if dry_run:
            print(f"  receipt      : s3://{s.bucket}/{receipt_key(key)}")
            print("Dry run — nothing was imported.")
            return
        self._ic_run("ova-to-ami",
                     lambda: self._ova_to_ami(s, key, name, launch, itype, key_name))

    def _ova_to_ami(self, s, key, name, launch, instance_type, key_name):
        from botocore.exceptions import ClientError
        s3 = self._ic_client("s3", s.region)
        ec2 = self._ic_client("ec2", s.region)

        try:
            head = s3.head_object(Bucket=s.bucket, Key=key)
        except ClientError:
            raise SystemExit(
                f"ova-to-ami: s3://{s.bucket}/{key} not found — stage the OVA "
                "first with the ova-fetch tool (or check the key)."
            )
        print(f"  source OVA   : {_fmt_bytes(head['ContentLength'])}")

        started = _utcnow_iso()
        t0 = time.monotonic()
        task = ec2.import_image(
            Description=name,
            DiskContainers=[{
                "Description": name,
                "Format": "ova",
                "UserBucket": {"S3Bucket": s.bucket, "S3Key": key},
            }],
        )
        task_id = task["ImportTaskId"]
        print(f"  import task  : {task_id} (typically 10–45 min)")

        ami_id, snapshot_ids = self._poll_import_task(ec2, task_id, t0)
        ec2.create_tags(Resources=[ami_id], Tags=[{"Key": "Name", "Value": name}])
        print(f"  AMI          : {ami_id} (snapshots: {', '.join(snapshot_ids) or '—'})")

        instance_id = public_ip = None
        if launch:
            instance_id, public_ip = self._launch_instance(
                ec2, ami_id, name, instance_type, key_name)

        receipt = {
            "tool": "ova-to-ami",
            "region": s.region,
            "source_bucket": s.bucket,
            "source_key": key,
            "source_size_bytes": head["ContentLength"],
            "import_task_id": task_id,
            "ami_id": ami_id,
            "ami_name": name,
            "snapshot_ids": snapshot_ids,
            "instance_id": instance_id,
            "instance_type": instance_type if launch else None,
            "public_ip": public_ip,
            "started_at": started,
            "completed_at": _utcnow_iso(),
            "duration_seconds": round(time.monotonic() - t0),
        }
        rkey = receipt_key(key)
        s3.put_object(Bucket=s.bucket, Key=rkey,
                      Body=json.dumps(receipt, indent=2).encode(),
                      ContentType="application/json")
        print(f"  receipt      : s3://{s.bucket}/{rkey}")

        print(f"Converted {Path(key).name} → {ami_id}"
              + (f", running as {instance_id} ({public_ip or 'no public IP'})"
                 if launch else " (no instance launched)"))
        if launch and public_ip:
            print(f"SSH (if the image's cloud-init took the EC2 keypair/datasource): "
                  f"ssh <user>@{public_ip}")
        print(f"Tear down later with ova-import-cleanup key={key}")

    def _poll_import_task(self, ec2, task_id, t0):
        """Poll describe-import-image-tasks until completion; return (ami, snaps)."""
        last = None
        while True:
            resp = ec2.describe_import_image_tasks(ImportTaskIds=[task_id])
            t = resp["ImportImageTasks"][0]
            status = t.get("Status", "")
            line = " ".join(x for x in (
                status,
                f"{t['Progress']}%" if t.get("Progress") else "",
                t.get("StatusMessage", ""),
            ) if x)
            if line != last:
                mins, secs = divmod(round(time.monotonic() - t0), 60)
                print(f"  [{mins:3d}:{secs:02d}] {line}")
                last = line
            if status == "completed":
                snaps = [d.get("SnapshotId") for d in t.get("SnapshotDetails", [])
                         if d.get("SnapshotId")]
                return t["ImageId"], snaps
            if status in ("deleted", "deleting"):
                raise SystemExit(
                    f"ova-to-ami: import task {task_id} failed — "
                    f"{t.get('StatusMessage', 'no status message')}"
                )
            if time.monotonic() - t0 > IMPORT_TIMEOUT_SECONDS:
                raise SystemExit(
                    f"ova-to-ami: gave up waiting after "
                    f"{IMPORT_TIMEOUT_SECONDS // 60} min — the AWS task is still "
                    f"running; check it with: aws ec2 describe-import-image-tasks "
                    f"--import-task-ids {task_id}"
                )
            time.sleep(IMPORT_POLL_SECONDS)

    def _ensure_ssh_sg(self, ec2):
        """Find or create the SSH-only security group in the default VPC."""
        from botocore.exceptions import ClientError
        try:
            resp = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [SSH_SG_NAME]}])
            if resp["SecurityGroups"]:
                return resp["SecurityGroups"][0]["GroupId"]
        except ClientError:
            pass
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
        if not vpcs["Vpcs"]:
            raise SystemExit(
                "ova-to-ami: no default VPC in this region — create one (or launch "
                "manually from the AMI) and re-run."
            )
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        sg = ec2.create_security_group(
            GroupName=SSH_SG_NAME, VpcId=vpc_id,
            Description="SSH-only access to OVA-imported instances (nce-safe-simulator)",
        )
        ec2.authorize_security_group_ingress(
            GroupId=sg["GroupId"],
            IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
            }],
        )
        print(f"  security grp : created {SSH_SG_NAME} ({sg['GroupId']}, SSH only)")
        return sg["GroupId"]

    def _launch_instance(self, ec2, ami_id, name, instance_type, key_name):
        sg_id = self._ensure_ssh_sg(ec2)
        kwargs = {
            "ImageId": ami_id,
            "InstanceType": instance_type,
            "MinCount": 1, "MaxCount": 1,
            "SecurityGroupIds": [sg_id],
            "TagSpecifications": [{
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": name}],
            }],
        }
        if key_name:
            kwargs["KeyName"] = key_name
        instance_id = ec2.run_instances(**kwargs)["Instances"][0]["InstanceId"]
        print(f"  instance     : {instance_id} launching ({instance_type}) …")

        t0 = time.monotonic()
        while True:
            inst = ec2.describe_instances(InstanceIds=[instance_id]
                                          )["Reservations"][0]["Instances"][0]
            state = inst["State"]["Name"]
            if state == "running":
                return instance_id, inst.get("PublicIpAddress")
            if state in ("terminated", "shutting-down"):
                raise SystemExit(
                    f"ova-to-ami: instance {instance_id} died while starting "
                    f"(state {state}) — the imported image may not boot on EC2."
                )
            if time.monotonic() - t0 > 15 * 60:
                print(f"  instance     : still '{state}' after 15 min — continuing "
                      "without waiting (check the EC2 console)")
                return instance_id, inst.get("PublicIpAddress")
            time.sleep(INSTANCE_POLL_SECONDS)

    # ------------------------------------------------------------------ #
    # ami-to-ova — the file-producing reverse
    # ------------------------------------------------------------------ #

    def _tool_ami_to_ova(self, source, bucket=None, fmt="vmdk", dry_run=False):
        """Export back to the bucket: an instance id (i-…) exports as a true
        .ova container; an AMI id (ami-…) exports as a VMDK/VHD/RAW disk image
        (AWS offers no OVA container for AMI-level export)."""
        s = self._ic_settings(bucket)
        source = source.strip()
        if source.startswith("i-"):
            mode = "instance → .ova"
        elif source.startswith("ami-"):
            mode = f"AMI → .{fmt}"
        else:
            raise SystemExit(
                f"ami-to-ova: source '{source}' is neither an instance id (i-…) "
                "nor an AMI id (ami-…)."
            )
        print(f"ami-to-ova — {source} ({mode})")
        print(f"  target: s3://{s.bucket}/{s.export_prefix}")
        if dry_run:
            print("Dry run — nothing was exported.")
            return
        self._ic_run("ami-to-ova", lambda: self._ami_to_ova(s, source, fmt))

    def _ami_to_ova(self, s, source, fmt):
        ec2 = self._ic_client("ec2", s.region)
        s3 = self._ic_client("s3", s.region)
        t0 = time.monotonic()

        if source.startswith("i-"):
            task = ec2.create_instance_export_task(
                Description=f"nce-safe-simulator export of {source}",
                InstanceId=source,
                TargetEnvironment="vmware",
                ExportToS3Task={
                    "ContainerFormat": "ova",
                    "DiskImageFormat": "VMDK",
                    "S3Bucket": s.bucket,
                    "S3Prefix": s.export_prefix,
                },
            )["ExportTask"]
            task_id = task["ExportTaskId"]
            print(f"  export task  : {task_id} (typically 10–40 min)")
            artifact = f"{s.export_prefix}{task_id}.ova"
            self._poll(lambda: ec2.describe_export_tasks(ExportTaskIds=[task_id])
                       ["ExportTasks"][0], "ami-to-ova", task_id, t0)
        else:
            task = ec2.export_image(
                ImageId=source,
                DiskImageFormat=fmt.upper(),
                RoleName=VMIMPORT_ROLE,
                S3ExportLocation={"S3Bucket": s.bucket, "S3Prefix": s.export_prefix},
            )
            task_id = task["ExportImageTaskId"]
            print(f"  export task  : {task_id} (typically 10–40 min)")
            artifact = f"{s.export_prefix}{task_id}.{fmt.lower()}"
            self._poll(lambda: ec2.describe_export_image_tasks(
                ExportImageTaskIds=[task_id])["ExportImageTasks"][0],
                "ami-to-ova", task_id, t0)

        head = s3.head_object(Bucket=s.bucket, Key=artifact)
        print(f"Exported {source} → s3://{s.bucket}/{artifact} "
              f"({_fmt_bytes(head['ContentLength'])})")

    def _poll(self, describe, label, task_id, t0):
        """Poll an export task dict until completed; both export APIs share the
        State/StatusMessage (instance) vs Status/StatusMessage (image) shape."""
        last = None
        while True:
            t = describe()
            status = t.get("State") or t.get("Status") or ""
            line = " ".join(x for x in (
                status,
                f"{t['Progress']}%" if t.get("Progress") else "",
                t.get("StatusMessage", ""),
            ) if x)
            if line != last:
                mins, secs = divmod(round(time.monotonic() - t0), 60)
                print(f"  [{mins:3d}:{secs:02d}] {line}")
                last = line
            if status == "completed":
                return
            if status in ("cancelled", "cancelling", "deleted", "deleting"):
                raise SystemExit(
                    f"{label}: export task {task_id} failed — "
                    f"{t.get('StatusMessage', 'no status message')}"
                )
            if time.monotonic() - t0 > IMPORT_TIMEOUT_SECONDS:
                raise SystemExit(
                    f"{label}: gave up waiting after {IMPORT_TIMEOUT_SECONDS // 60} "
                    f"min — the AWS task {task_id} is still running; check the EC2 "
                    "console (Export tasks)."
                )
            time.sleep(EXPORT_POLL_SECONDS)

    # ------------------------------------------------------------------ #
    # ova-import-cleanup — tear an import down again
    # ------------------------------------------------------------------ #

    def _tool_ova_import_cleanup(self, key=None, bucket=None, ami_id=None,
                                 instance_id=None, delete_staged=False, dry_run=False):
        """Terminate the instance, deregister the AMI, delete its snapshots.

        Targets come from the receipt written by ova-to-ami (via *key*) and/or
        the explicit ids; explicit ids win. delete_staged also removes the
        staged OVA and the receipt itself.
        """
        if not (key or ami_id or instance_id):
            raise SystemExit(
                "ova-import-cleanup: nothing to clean — give the source OVA key "
                "(to read its receipt) or an explicit ami_id / instance_id."
            )
        bucket, key = split_s3_key(key, bucket)
        s = self._ic_settings(bucket)
        self._ic_run("ova-import-cleanup",
                     lambda: self._ova_import_cleanup(
                         s, key, ami_id, instance_id, delete_staged, dry_run))

    def _ova_import_cleanup(self, s, key, ami_id, instance_id, delete_staged, dry_run):
        from botocore.exceptions import ClientError
        s3 = self._ic_client("s3", s.region)
        ec2 = self._ic_client("ec2", s.region)

        snapshot_ids = []
        receipt = None
        if key:
            rkey = receipt_key(key)
            try:
                receipt = json.loads(
                    s3.get_object(Bucket=s.bucket, Key=rkey)["Body"].read())
                print(f"ova-import-cleanup — receipt s3://{s.bucket}/{rkey}")
            except ClientError:
                print(f"ova-import-cleanup — no receipt at s3://{s.bucket}/{rkey} "
                      "(falling back to explicit ids)")
            if receipt:
                ami_id = ami_id or receipt.get("ami_id")
                instance_id = instance_id or receipt.get("instance_id")
                snapshot_ids = receipt.get("snapshot_ids") or []

        # -- instance --------------------------------------------------- #
        if instance_id:
            if dry_run:
                print(f"  would terminate instance {instance_id}")
            else:
                try:
                    ec2.terminate_instances(InstanceIds=[instance_id])
                    print(f"  terminating {instance_id} …")
                    t0 = time.monotonic()
                    while time.monotonic() - t0 < 10 * 60:
                        inst = ec2.describe_instances(InstanceIds=[instance_id]
                                                      )["Reservations"][0]["Instances"][0]
                        if inst["State"]["Name"] == "terminated":
                            break
                        time.sleep(INSTANCE_POLL_SECONDS)
                    print(f"  instance {instance_id}: terminated")
                except ClientError as exc:
                    print(f"  instance {instance_id}: {exc.response['Error'].get('Code')} "
                          "(already gone?) — continuing")

        # -- AMI + snapshots -------------------------------------------- #
        if ami_id:
            try:
                images = ec2.describe_images(ImageIds=[ami_id])["Images"]
                for bdm in (images[0].get("BlockDeviceMappings", []) if images else []):
                    sid = bdm.get("Ebs", {}).get("SnapshotId")
                    if sid and sid not in snapshot_ids:
                        snapshot_ids.append(sid)
            except ClientError:
                images = []
            if dry_run:
                print(f"  would deregister {ami_id} and delete snapshots: "
                      f"{', '.join(snapshot_ids) or '—'}")
            elif not images:
                print(f"  AMI {ami_id}: not found (already deregistered?) — continuing")
            else:
                ec2.deregister_image(ImageId=ami_id)
                print(f"  AMI {ami_id}: deregistered")
        if not dry_run:
            for sid in snapshot_ids:
                try:
                    ec2.delete_snapshot(SnapshotId=sid)
                    print(f"  snapshot {sid}: deleted")
                except ClientError as exc:
                    print(f"  snapshot {sid}: {exc.response['Error'].get('Code')} "
                          "(already gone?) — continuing")

        # -- staged objects --------------------------------------------- #
        if key and delete_staged:
            if dry_run:
                print(f"  would delete s3://{s.bucket}/{key} and its receipt")
            else:
                s3.delete_object(Bucket=s.bucket, Key=key)
                s3.delete_object(Bucket=s.bucket, Key=receipt_key(key))
                print(f"  deleted s3://{s.bucket}/{key} (+ receipt)")

        print("Dry run — nothing was changed." if dry_run else "Cleanup complete.")
