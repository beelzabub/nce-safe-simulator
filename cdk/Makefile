.PHONY: install bootstrap set-vpc diff deploy destroy seed-config ecr-push ecs-redeploy ecs-logs ecs-exec grafana-setup grafana-deploy grafana-add-user full-deploy redeploy help
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk -F':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: ## Install CDK CLI and Python CDK dependencies (run once)
	npm install -g aws-cdk
	pip install -r requirements.txt

bootstrap: ## Bootstrap CDK for this AWS account/region (run once per account+region)
	cdk bootstrap

set-vpc: ## Discover the VPC from the 'powers-dev' EC2 instance and save it to cdk.json
	@VPC_ID=$$(aws ec2 describe-instances --filters "Name=tag:Name,Values=powers-dev" "Name=instance-state-name,Values=running,stopped" --query 'Reservations[0].Instances[0].VpcId' --output text) && \
	[ "$$VPC_ID" != "None" ] && [ -n "$$VPC_ID" ] || { echo "ERROR: no running/stopped EC2 instance named 'powers-dev' found"; exit 1; } && \
	jq --arg v "$$VPC_ID" '.context.vpc_id = $$v' cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json && \
	echo "vpc_id set to $$VPC_ID"

diff: ## Show what CDK will change without deploying
	cdk diff

deploy: ## Deploy (or update) the full AWS stack
	@ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	REPO="$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com/$$APP_NAME" && \
	IMAGE_COUNT=$$(aws ecr list-images --repository-name $$APP_NAME --region $$REGION --query 'length(imageIds)' --output text 2>/dev/null || echo "0") && \
	if [ "$$IMAGE_COUNT" = "0" ]; then \
	  echo "==> No image in ECR — deploying infra with service scaled to 0..." && \
	  cdk deploy --require-approval never --context desired_count=0 && \
	  echo "==> Building and pushing initial image..." && \
	  aws ecr get-login-password --region $$REGION | docker login --username AWS --password-stdin "$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com" && \
	  docker build --platform linux/arm64 -t $$APP_NAME ../ && \
	  docker tag $$APP_NAME:latest "$$REPO:latest" && \
	  docker push "$$REPO:latest" && \
	  echo "==> Image ready — scaling service up..."; \
	fi && \
	cdk deploy --require-approval never

destroy: ## Tear down all AWS resources (EFS and CloudWatch logs are retained)
	cdk destroy --force

seed-config: ## Store config.json in SSM as a SecureString (re-run to update)
	@echo "Storing config.json in SSM as SecureString /nce/config..."
	aws ssm put-parameter --name /nce/config --type SecureString --overwrite --value "$$(cat ../config.json)"
	@echo "Done. Run 'make ecs-redeploy' to pick up the new config."

ecr-push: ## Build and push :latest to ECR (follow with ecs-redeploy)
	@ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	REPO="$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com/nce-safe-simulator" && \
	aws ecr get-login-password --region $$REGION | docker login --username AWS --password-stdin "$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com" && \
	docker build --platform linux/arm64 -t nce-safe-simulator ../ && \
	docker tag nce-safe-simulator:latest "$$REPO:latest" && \
	docker push "$$REPO:latest" && \
	echo "Pushed $$REPO:latest — run 'make ecs-redeploy' to activate."

ecs-redeploy: ## Force a new ECS deployment (picks up a freshly pushed image)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	aws ecs update-service --cluster nce --service nce-safe-simulator \
	  --region $$REGION --force-new-deployment --output text --query 'service.serviceArn'

ecs-logs: ## Tail live ECS container logs
	aws logs tail /ecs/nce-safe-simulator --follow

ecs-exec: ## Open an interactive shell in the running Fargate task via ECS Exec
	@CLUSTER=$$(jq -r '.context.cluster_name' cdk.json) && \
	SERVICE=$$(jq -r '.context.app_name' cdk.json) && \
	CONTAINER=$$(jq -r '.context.container_name' cdk.json) && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	TASK=$$(aws ecs list-tasks --cluster $$CLUSTER --service-name $$SERVICE \
	  --region $$REGION --query 'taskArns[0]' --output text) && \
	aws ecs execute-command --cluster $$CLUSTER --task $$TASK \
	  --container $$CONTAINER --region $$REGION --interactive --command /bin/sh

grafana-setup: ## Create Grafana Admin API key and store in SSM (idempotent)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	WORKSPACE_ID=$$(aws grafana list-workspaces --region $$REGION \
	  --query "workspaces[?name=='$$(jq -r '.context.app_name' cdk.json)'].id" \
	  --output text) && \
	[ -n "$$WORKSPACE_ID" ] || { echo "ERROR: Grafana workspace not found — run make deploy first"; exit 1; } && \
	echo "==> Rotating Grafana Admin API key in workspace $$WORKSPACE_ID..." && \
	aws grafana delete-workspace-api-key --key-name "nce-deploy" \
	  --workspace-id $$WORKSPACE_ID --region $$REGION 2>/dev/null || true && \
	KEY=$$(aws grafana create-workspace-api-key \
	  --key-name "nce-deploy" \
	  --key-role "ADMIN" \
	  --seconds-to-live 2592000 \
	  --workspace-id $$WORKSPACE_ID \
	  --region $$REGION \
	  --query 'key' --output text) && \
	PARAM=$$(jq -r '.context.grafana_api_key_param' cdk.json) && \
	aws ssm put-parameter --name $$PARAM --type SecureString --overwrite \
	  --value "$$KEY" --region $$REGION && \
	echo "==> API key stored in SSM at $$PARAM (valid 90 days). Run 'make grafana-deploy' to push dashboards."

grafana-deploy: ## Install Infinity plugin, configure datasource, and deploy all dashboards (idempotent)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	WORKSPACE_ID=$$(aws grafana list-workspaces --region $$REGION \
	  --query "workspaces[?name=='$$APP_NAME'].id" --output text) && \
	[ -n "$$WORKSPACE_ID" ] || { echo "ERROR: Grafana workspace not found — run make deploy first"; exit 1; } && \
	PARAM=$$(jq -r '.context.grafana_api_key_param' cdk.json) && \
	API_KEY=$$(aws ssm get-parameter --name $$PARAM --with-decryption \
	  --region $$REGION --query 'Parameter.Value' --output text) && \
	GRAFANA_URL="https://$$WORKSPACE_ID.grafana-workspace.$$REGION.amazonaws.com" && \
	DATA_URL="$$(aws cloudformation describe-stacks --stack-name NceStack --region $$REGION \
	  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontUrl`].OutputValue' \
	  --output text)" && \
	[ -n "$$DATA_URL" ] || { echo "ERROR: could not resolve CloudFrontUrl from NceStack outputs"; exit 1; } && \
	echo "==> Installing Infinity plugin..." && \
	PLUGIN_STATUS=$$(curl -s "$$GRAFANA_URL/api/plugins/yesoreyeram-infinity-datasource/settings" \
	  -H "Authorization: Bearer $$API_KEY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('info',{}).get('version',''))" 2>/dev/null) && \
	if [ -n "$$PLUGIN_STATUS" ]; then \
	  echo "  Infinity plugin already installed (v$$PLUGIN_STATUS)"; \
	else \
	  INSTALL_CODE=$$(curl -s -o /dev/null -w "%{http_code}" -X POST \
	    "$$GRAFANA_URL/api/plugins/yesoreyeram-infinity-datasource/install" \
	    -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	    -d '{"version":"2.11.0"}') && \
	  [ "$$INSTALL_CODE" = "200" ] || { echo "ERROR: plugin install returned HTTP $$INSTALL_CODE"; exit 1; }; \
	  echo "  Installed yesoreyeram-infinity-datasource 2.11.0"; \
	fi && \
	echo "==> Configuring Infinity datasource..." && \
	DS_PAYLOAD="{\"uid\":\"ffon28bht91c0b\",\"name\":\"Infinity\",\"type\":\"yesoreyeram-infinity-datasource\",\"access\":\"direct\",\"isDefault\":true,\"url\":\"$$DATA_URL\",\"jsonData\":{}}" && \
	EXISTING_DS=$$(curl -sf "$$GRAFANA_URL/api/datasources/name/Infinity" \
	  -H "Authorization: Bearer $$API_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "") && \
	if [ -n "$$EXISTING_DS" ]; then \
	  curl -sf -X PUT "$$GRAFANA_URL/api/datasources/$$EXISTING_DS" \
	    -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	    -d "$$DS_PAYLOAD" > /dev/null && echo "  Updated datasource (id=$$EXISTING_DS, uid=ffon28bht91c0b, url=$$DATA_URL)"; \
	else \
	  curl -sf -X POST "$$GRAFANA_URL/api/datasources" \
	    -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	    -d "$$DS_PAYLOAD" > /dev/null && echo "  Created datasource (uid=ffon28bht91c0b, url=$$DATA_URL)"; \
	fi && \
	echo "==> Deploying dashboards..." && \
	find ../grafana -name '*.json' | while read DASH; do \
	  PATCHED=$$(cat "$$DASH" | sed "s|__BASE_URL__|$$DATA_URL|g") && \
	  TITLE=$$(echo "$$PATCHED" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title','unknown'))") && \
	  RESULT=$$(echo "{\"dashboard\":$$PATCHED,\"overwrite\":true,\"folderId\":0}" | \
	    curl -sf -X POST "$$GRAFANA_URL/api/dashboards/import" \
	      -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	      -d @- 2>&1) && \
	  echo "  ✓ $$TITLE" || echo "  ✗ $$TITLE: $$RESULT"; \
	done && \
	echo "==> Done. Datasource URL: $$DATA_URL — Open $$GRAFANA_URL"

grafana-add-user: ## Assign Grafana Admin role to the SSO user defined in cdk.json (idempotent)
	bash scripts/add-grafana-user.sh

full-deploy: ## Deploy CDK stack then configure Grafana end-to-end (fresh stack after destroy)
	@$(MAKE) --no-print-directory deploy
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	PARAM=$$(jq -r '.context.grafana_api_key_param' cdk.json) && \
	echo "==> Waiting for Grafana workspace to reach ACTIVE (up to 20 min)..." && \
	STATUS="" && i=0 && \
	while [ $$i -lt 40 ]; do \
	  STATUS=$$(aws grafana list-workspaces --region $$REGION \
	    --query "workspaces[?name=='$$APP_NAME'].status" --output text 2>/dev/null); \
	  [ "$$STATUS" = "ACTIVE" ] && break; \
	  i=$$((i+1)); \
	  printf "  [%02d/40] %-12s — waiting 30s...\n" $$i "$${STATUS:-pending}"; \
	  sleep 30; \
	done && \
	[ "$$STATUS" = "ACTIVE" ] || { echo "ERROR: workspace did not become ACTIVE after 20 min"; exit 1; } && \
	$(MAKE) --no-print-directory grafana-setup
	@$(MAKE) --no-print-directory grafana-deploy
	@$(MAKE) --no-print-directory grafana-add-user

redeploy: ## Full teardown and redeploy — safe to run unattended (nohup make redeploy > redeploy.log 2>&1 &)
	bash scripts/redeploy.sh
