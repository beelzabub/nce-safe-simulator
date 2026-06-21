.PHONY: install bootstrap set-vpc diff deploy destroy seed-config ecs-redeploy ecs-logs

## Install CDK CLI and Python CDK dependencies (run once)
install:
	npm install -g aws-cdk
	pip install -r requirements.txt

## Bootstrap CDK for this AWS account/region (run once per account+region)
bootstrap:
	cdk bootstrap

## Discover the VPC from the 'powers-dev' EC2 instance and save it to cdk.json
set-vpc:
	@VPC_ID=$$(aws ec2 describe-instances --filters "Name=tag:Name,Values=powers-dev" "Name=instance-state-name,Values=running,stopped" --query 'Reservations[0].Instances[0].VpcId' --output text) && \
	[ "$$VPC_ID" != "None" ] && [ -n "$$VPC_ID" ] || { echo "ERROR: no running/stopped EC2 instance named 'powers-dev' found"; exit 1; } && \
	jq --arg v "$$VPC_ID" '.context.vpc_id = $$v' cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json && \
	echo "vpc_id set to $$VPC_ID"

## Show what CDK will change without deploying
diff:
	cdk diff

## Deploy (or update) the full AWS stack — builds image, pushes to ECR, provisions infra
deploy:
	cdk deploy --require-approval never

## Tear down all AWS resources (EFS and CloudWatch logs are retained)
destroy:
	cdk destroy --force

## Store config.json in SSM as a SecureString (run once after deploy; re-run to update)
seed-config:
	@echo "Storing config.json in SSM as SecureString /nce/config..."
	aws ssm put-parameter --name /nce/config --type SecureString --overwrite --value "$$(cat ../config.json)"
	@echo "Done. Run 'make ecs-redeploy' to pick up the new config."

## Force a new ECS deployment (picks up a freshly pushed image without a full CDK run)
ecs-redeploy:
	aws ecs update-service --cluster nce --service nce-safe-simulator \
	  --force-new-deployment --output text --query 'service.serviceArn'

## Tail live ECS container logs
ecs-logs:
	aws logs tail /ecs/nce-safe-simulator --follow
