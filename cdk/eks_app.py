import os
import json
import aws_cdk as cdk
from nce_eks_stack import NceEksStack

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "cdk-eks.json")) as _f:
    _cfg = json.load(_f)

app = cdk.App()
for _k, _v in _cfg.get("context", {}).items():
    if app.node.try_get_context(_k) is None:
        app.node.set_context(_k, _v)

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

NceEksStack(app, "NceEksStack", env=env)

app.synth()
