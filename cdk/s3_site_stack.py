"""Private S3 bucket + CloudFront distribution with Origin Access Control.

Issue #216, decision A1 (locked): CloudFront + private bucket via OAC. This is
the declarative CDK equivalent of the runtime boto3 path in
``server/deploy_s3.py`` — it provisions the identical topology (all public
access blocked, the bucket readable only through the distribution). Object sync
is handled by the deploy job (``server/deploy_s3.sync_site``), not this stack.

Operators who prefer infrastructure-as-code deploy with ``make s3-deploy``;
the durable-job path (``NceGitLab.py --deploy-s3 publish``) needs no CDK
toolchain and is what the server launches.
"""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
)
from constructs import Construct


class NceS3SiteStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ctx = self.node.try_get_context
        bucket_name = ctx("site_bucket")
        comment = ctx("distribution_comment") or "NCE SAFe Simulator static site"

        # Private bucket — no public access, HTTPS enforced. auto_delete_objects
        # gives `cdk destroy` the "empty bucket + delete" semantics the issue's
        # destroy step requires.
        bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # with_origin_access_control creates the OAC and scopes the bucket
        # policy to this distribution — no public bucket, no legacy OAI.
        distribution = cloudfront.Distribution(
            self,
            "SiteDistribution",
            comment=comment,
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                compress=True,
            ),
        )

        CfnOutput(
            self,
            "SiteUrl",
            value=f"https://{distribution.distribution_domain_name}",
        )
        CfnOutput(self, "SiteBucketName", value=bucket.bucket_name)
