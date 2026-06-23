import os
import aws_cdk as cdk
from nce_ecs_stack import NceEcsStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

NceEcsStack(app, "NceStack", env=env)

app.synth()
