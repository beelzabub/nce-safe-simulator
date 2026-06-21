import os
import aws_cdk as cdk
from nce_stack import NceStack

app = cdk.App()

NceStack(
    app,
    "NceStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
