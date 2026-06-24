import os
import aws_cdk as cdk
from nce_eks_stack import NceEksStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

NceEksStack(app, "NceEksStack", env=env)

app.synth()
