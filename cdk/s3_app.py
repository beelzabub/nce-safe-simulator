import os
import json
import aws_cdk as cdk
from s3_site_stack import NceS3SiteStack

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "cdk-s3.json")) as _f:
    _cfg = json.load(_f)

app = cdk.App()
for _k, _v in _cfg.get("context", {}).items():
    # Only fill in values not already supplied by the CLI (--context wins)
    if app.node.try_get_context(_k) is None:
        app.node.set_context(_k, _v)

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    # CloudFront distributions are global; the stack must synth in us-east-1.
    region=os.environ.get("CDK_DEFAULT_REGION") or "us-east-1",
)

NceS3SiteStack(app, "NceS3SiteStack", env=env)

app.synth()
