.PHONY: install bootstrap set-vpc set-efs ecs-diff ecs-deploy ecs-destroy seed-config ecr-push ecs-redeploy ecs-logs ecs-exec grafana-setup ecs-grafana-deploy grafana-add-user ecs-full-deploy ecs-full-redeploy eks-install eks-deploy eks-kubeconfig eks-lb-controller eks-helm-install eks-helm-upgrade eks-set-alb eks-cloudfront-deploy eks-grafana-deploy eks-redeploy eks-logs eks-exec eks-full-deploy eks-full-redeploy eks-destroy eks-diagram ecs-diagram help
.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n"} /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

##@ Setup (run once per account)
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

set-efs: ## Read EFS ID, SG, and access-point IDs from NceStack and write to cdk.json
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	EFS_ID=$$(aws cloudformation describe-stacks --stack-name NceStack --region $$REGION \
	  --query 'Stacks[0].Outputs[?OutputKey==`EfsId`].OutputValue' --output text) && \
	[ -n "$$EFS_ID" ] || { echo "ERROR: EfsId not found in NceStack outputs — run make ecs-deploy first"; exit 1; } && \
	echo "==> EFS ID: $$EFS_ID" && \
	AP_JSON=$$(aws efs describe-access-points --file-system-id $$EFS_ID --region $$REGION \
	  --query 'AccessPoints[].{id:AccessPointId,path:RootDirectory.Path}' --output json) && \
	AP_CONFIG=$$(echo "$$AP_JSON" | python3 -c "import sys,json; aps=json.load(sys.stdin); print(next(a['id'] for a in aps if a['path']=='/config'))") && \
	AP_REPORTS=$$(echo "$$AP_JSON" | python3 -c "import sys,json; aps=json.load(sys.stdin); print(next(a['id'] for a in aps if a['path']=='/reports'))") && \
	AP_INTERACTIVE=$$(echo "$$AP_JSON" | python3 -c "import sys,json; aps=json.load(sys.stdin); print(next(a['id'] for a in aps if a['path']=='/interactive'))") && \
	AP_QUARTO=$$(echo "$$AP_JSON" | python3 -c "import sys,json; aps=json.load(sys.stdin); print(next(a['id'] for a in aps if a['path']=='/quarto-site'))") && \
	MT_ID=$$(aws efs describe-mount-targets --file-system-id $$EFS_ID --region $$REGION \
	  --query 'MountTargets[0].MountTargetId' --output text) && \
	EFS_SG_ID=$$(aws efs describe-mount-target-security-groups --mount-target-id $$MT_ID --region $$REGION \
	  --query 'SecurityGroups[0]' --output text) && \
	jq --arg eid "$$EFS_ID" \
	   --arg esg "$$EFS_SG_ID" \
	   --arg apc "$$AP_CONFIG" \
	   --arg apr "$$AP_REPORTS" \
	   --arg api "$$AP_INTERACTIVE" \
	   --arg apq "$$AP_QUARTO" \
	   '.context.efs_id = $$eid | .context.efs_sg_id = $$esg | .context.efs_ap_config = $$apc | .context.efs_ap_reports = $$apr | .context.efs_ap_interactive = $$api | .context.efs_ap_quarto = $$apq' \
	   cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json && \
	echo "EFS config written to cdk.json (efs_id=$$EFS_ID, efs_sg_id=$$EFS_SG_ID)"

##@ ECS / Fargate
ecs-diff: ## Show what ECS CDK stack will change without deploying
	cdk diff NceStack --app "python ecs_app.py"

ecs-deploy: ## Deploy (or update) the ECS stack
	@ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	REPO="$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com/$$APP_NAME" && \
	IMAGE_COUNT=$$(aws ecr list-images --repository-name $$APP_NAME --region $$REGION --query 'length(imageIds)' --output text 2>/dev/null || echo "0") && \
	if [ "$$IMAGE_COUNT" = "0" ]; then \
	  echo "==> No image in ECR — deploying infra with service scaled to 0..." && \
	  cdk deploy NceStack --app "python ecs_app.py" --require-approval never --context desired_count=0 && \
	  echo "==> Building and pushing initial image..." && \
	  aws ecr get-login-password --region $$REGION | docker login --username AWS --password-stdin "$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com" && \
	  docker build --platform linux/arm64 -t $$APP_NAME ../ && \
	  docker tag $$APP_NAME:latest "$$REPO:latest" && \
	  docker push "$$REPO:latest" && \
	  echo "==> Image ready — scaling service up..."; \
	fi && \
	cdk deploy NceStack --app "python ecs_app.py" --require-approval never

ecs-destroy: ## Tear down ECS stack (EFS and CloudWatch logs are retained)
	cdk destroy NceStack --app "python ecs_app.py" --force

##@ Shared
eks-diagram: ## Regenerate EKS architecture PNG from cdk.out/tree.json (requires cdk synth to have run)
	@mkdir -p ../public/architecture
	@npx --prefix . cdk-dia --stacks NceEksStack \
	  --target-path $$(pwd)/../public/architecture/eks-architecture.png
	@echo "==> ../public/architecture/eks-architecture.png"

ecs-diagram: ## Regenerate ECS architecture PNG from cdk-ecs.out/tree.json
	@mkdir -p ../public/architecture
	@npx --prefix . cdk-dia --cdk-tree-path cdk-ecs.out/tree.json --stacks NceStack \
	  --target-path $$(pwd)/../public/architecture/ecs-architecture.png
	@echo "==> ../public/architecture/ecs-architecture.png"

seed-config: ## Store config.json in SSM as a SecureString (re-run to update)
	@echo "Storing config.json in SSM as SecureString /nce/config..."
	aws ssm put-parameter --name /nce/config --type SecureString --overwrite --value "$$(cat ../config.json)"
	@echo "Done. Run 'make ecs-redeploy' to pick up the new config."

ecr-push: ## Build and push :latest to ECR (follow with ecs-redeploy or eks-redeploy)
	@ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	REPO="$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com/nce-safe-simulator" && \
	aws ecr get-login-password --region $$REGION | docker login --username AWS --password-stdin "$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com" && \
	docker build --platform linux/arm64 -t nce-safe-simulator ../ && \
	docker tag nce-safe-simulator:latest "$$REPO:latest" && \
	docker push "$$REPO:latest" && \
	echo "Pushed $$REPO:latest — run 'make ecs-redeploy' or 'make eks-redeploy' to activate."

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
	echo "==> API key stored in SSM at $$PARAM (valid 90 days). Run 'make ecs-grafana-deploy' or 'make eks-grafana-deploy' to push dashboards."

ecs-grafana-deploy: ## Install Infinity plugin, configure ECS datasource, and deploy all dashboards (idempotent)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	WORKSPACE_ID=$$(aws grafana list-workspaces --region $$REGION \
	  --query "workspaces[?name=='$$APP_NAME'].id" --output text) && \
	[ -n "$$WORKSPACE_ID" ] || { echo "ERROR: Grafana workspace not found — run make ecs-deploy first"; exit 1; } && \
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

ecs-full-deploy: ## Deploy ECS CDK stack then configure Grafana end-to-end (fresh stack after ecs-destroy)
	@$(MAKE) --no-print-directory ecs-deploy
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
	@$(MAKE) --no-print-directory ecs-grafana-deploy
	@$(MAKE) --no-print-directory grafana-add-user

ecs-full-redeploy: ## Full ECS teardown and redeploy — safe to run unattended (nohup make ecs-full-redeploy > redeploy-ecs.log 2>&1 &)
	bash scripts/redeploy-ecs.sh

##@ EKS / Kubernetes
eks-install: ## Download and create LB Controller IAM policy (once per AWS account)
	@POLICY_FILE=$$(mktemp) && \
	curl -sL https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json \
	  -o "$$POLICY_FILE" && \
	aws iam create-policy --policy-name AWSLoadBalancerControllerIAMPolicy \
	  --policy-document file://"$$POLICY_FILE" && \
	rm "$$POLICY_FILE" && \
	echo "AWSLoadBalancerControllerIAMPolicy created."

eks-deploy: ## Deploy EKS CDK stack (cluster, node group, LB controller, EFS CSI driver)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	CDK_DEFAULT_ACCOUNT=$$ACCOUNT CDK_DEFAULT_REGION=$$REGION \
	cdk deploy NceEksStack --app "python eks_app.py" --require-approval never

eks-tag-subnets: ## Tag VPC public subnets so the LB controller can provision internet-facing ALBs
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	VPC_ID=$$(jq -r '.context.vpc_id' cdk.json) && \
	SUBNETS=$$(aws ec2 describe-subnets --region $$REGION \
	  --filters "Name=vpc-id,Values=$$VPC_ID" "Name=map-public-ip-on-launch,Values=true" \
	  --query 'Subnets[*].SubnetId' --output text) && \
	[ -n "$$SUBNETS" ] || { echo "ERROR: no public subnets found in $$VPC_ID"; exit 1; } && \
	aws ec2 create-tags --region $$REGION --resources $$SUBNETS \
	  --tags Key=kubernetes.io/role/elb,Value=1 && \
	echo "Tagged subnets: $$SUBNETS"

eks-kubeconfig: ## Configure kubectl to talk to the EKS cluster
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	CLUSTER=$$(jq -r '.context.eks_cluster_name' cdk.json) && \
	aws eks update-kubeconfig --name $$CLUSTER --region $$REGION

eks-lb-controller: ## Install AWS Load Balancer Controller via Helm (run after eks-kubeconfig)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	CLUSTER=$$(jq -r '.context.eks_cluster_name' cdk.json) && \
	VPC_ID=$$(jq -r '.context.vpc_id' cdk.json) && \
	helm repo add eks https://aws.github.io/eks-charts 2>/dev/null || true && \
	helm repo update eks && \
	helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
	  --namespace kube-system \
	  --set clusterName=$$CLUSTER \
	  --set serviceAccount.create=false \
	  --set serviceAccount.name=aws-load-balancer-controller \
	  --set region=$$REGION \
	  --set vpcId=$$VPC_ID && \
	echo "==> AWS Load Balancer Controller installed."

eks-helm-install: ## Install the nce Helm chart (reads ECR repo and EFS IDs from NceEksStack outputs)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	REPO="$$ACCOUNT.dkr.ecr.$$REGION.amazonaws.com/$$APP_NAME" && \
	OUTPUTS=$$(aws cloudformation describe-stacks --stack-name NceEksStack --region $$REGION \
	  --query 'Stacks[0].Outputs' --output json) && \
	_out() { echo "$$OUTPUTS" | python3 -c "import sys,json; o=json.load(sys.stdin); print(next(x['OutputValue'] for x in o if x['OutputKey']=='$$1'))"; } && \
	SA_ROLE_ARN=$$(_out EksAppSaRoleArn) && \
	EFS_ID=$$(_out EfsId) && \
	AP_CONFIG=$$(_out EfsApConfig) && \
	AP_REPORTS=$$(_out EfsApReports) && \
	AP_INTERACTIVE=$$(_out EfsApInteractive) && \
	AP_QUARTO=$$(_out EfsApQuartoSite) && \
	ALB_SG_ID=$$(_out AlbSgId) && \
	helm upgrade --install $$APP_NAME ../helm/nce-safe-simulator \
	  --namespace $$NAMESPACE --create-namespace \
	  --set image.repository=$$REPO \
	  --set serviceAccount.roleArn=$$SA_ROLE_ARN \
	  --set efs.fileSystemId=$$EFS_ID \
	  --set efs.accessPoints.config=$$AP_CONFIG \
	  --set efs.accessPoints.reports=$$AP_REPORTS \
	  --set efs.accessPoints.interactive=$$AP_INTERACTIVE \
	  --set efs.accessPoints.quartoSite=$$AP_QUARTO \
	  --set ingress.albSgId=$$ALB_SG_ID && \
	echo "Helm release installed in namespace $$NAMESPACE."

eks-helm-upgrade: ## Upgrade the Helm release (new values; use eks-redeploy for image updates)
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	helm upgrade $$APP_NAME ../helm/nce-safe-simulator --namespace $$NAMESPACE

eks-set-alb: ## Read EKS ALB DNS from ingress and write to cdk.json (polls up to 5 min)
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	echo "==> Waiting for ALB to be provisioned (up to 5 min)..." && \
	ALB_DNS="" && \
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
	  ALB_DNS=$$(kubectl get ingress -n $$NAMESPACE $$APP_NAME \
	    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true) && \
	  [ -n "$$ALB_DNS" ] && break; \
	  echo "  [$$i/30] Not ready yet, waiting 10s..."; \
	  sleep 10; \
	done && \
	[ -n "$$ALB_DNS" ] || { echo "ERROR: ALB DNS still not available after 5 min"; exit 1; } && \
	jq --arg v "$$ALB_DNS" '.context.eks_alb_dns = $$v' cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json && \
	echo "==> eks_alb_dns set to $$ALB_DNS"

eks-cloudfront-deploy: ## Create or update CloudFront distribution in front of EKS ALB
	@ALB_DNS=$$(jq -r '.context.eks_alb_dns // empty' cdk.json) && \
	[ -n "$$ALB_DNS" ] || { echo "ERROR: eks_alb_dns not set — run make eks-set-alb first"; exit 1; } && \
	EXISTING_ID=$$(jq -r '.context.eks_cf_distribution_id // empty' cdk.json) && \
	DIST_CONFIG=$$(jq -nc --arg alb "$$ALB_DNS" \
	  '{"CallerReference":"nce-eks-alb","Comment":"NCE Safe Simulator EKS","DefaultCacheBehavior":{"TargetOriginId":"nce-eks-alb","ViewerProtocolPolicy":"https-only","CachePolicyId":"4135ea2d-6df8-44a3-9df3-4b5a84be39ad","OriginRequestPolicyId":"b689b0a8-53d0-40ab-baf2-68738e2966ac","AllowedMethods":{"Quantity":7,"Items":["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],"CachedMethods":{"Quantity":2,"Items":["GET","HEAD"]}},"Compress":true},"Origins":{"Quantity":1,"Items":[{"Id":"nce-eks-alb","DomainName":$alb,"CustomOriginConfig":{"HTTPPort":80,"HTTPSPort":443,"OriginProtocolPolicy":"http-only"}}]},"Enabled":true,"HttpVersion":"http2"}') && \
	if [ -n "$$EXISTING_ID" ]; then \
	  echo "==> Updating existing distribution $$EXISTING_ID..." && \
	  ETAG=$$(aws cloudfront get-distribution-config --id "$$EXISTING_ID" \
	    --query 'ETag' --output text) && \
	  aws cloudfront update-distribution --id "$$EXISTING_ID" --if-match "$$ETAG" \
	    --distribution-config "$$DIST_CONFIG" > /dev/null && \
	  echo "Distribution $$EXISTING_ID updated."; \
	else \
	  echo "==> Creating CloudFront distribution for EKS ALB ($$ALB_DNS)..." && \
	  RESULT=$$(aws cloudfront create-distribution --distribution-config "$$DIST_CONFIG") && \
	  CF_ID=$$(echo "$$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['Id'])") && \
	  CF_DOMAIN=$$(echo "$$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['DomainName'])") && \
	  jq --arg id "$$CF_ID" --arg url "https://$$CF_DOMAIN" \
	    '.context.eks_cf_distribution_id = $$id | .context.eks_cf_url = $$url' \
	    cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json && \
	  echo "==> Distribution created: https://$$CF_DOMAIN (may take ~5 min to become active)"; \
	fi

eks-grafana-deploy: ## Install Infinity plugin, configure EKS datasource, and deploy all dashboards (idempotent)
	@REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	WORKSPACE_ID=$$(aws grafana list-workspaces --region $$REGION \
	  --query "workspaces[?name=='$$APP_NAME'].id" --output text) && \
	[ -n "$$WORKSPACE_ID" ] || { echo "ERROR: Grafana workspace not found"; exit 1; } && \
	PARAM=$$(jq -r '.context.grafana_api_key_param' cdk.json) && \
	API_KEY=$$(aws ssm get-parameter --name $$PARAM --with-decryption \
	  --region $$REGION --query 'Parameter.Value' --output text) && \
	GRAFANA_URL="https://$$WORKSPACE_ID.grafana-workspace.$$REGION.amazonaws.com" && \
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
	  [ "$$INSTALL_CODE" = "200" ] || { echo "ERROR: plugin install returned HTTP $$INSTALL_CODE"; exit 1; } && \
	  echo "  Installed yesoreyeram-infinity-datasource 2.11.0"; \
	fi && \
	DATA_URL=$$(aws cloudformation describe-stacks --stack-name NceEksStack --region $$REGION \
	  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontUrl`].OutputValue' --output text) && \
	[ -n "$$DATA_URL" ] || { echo "ERROR: CloudFrontUrl not in NceEksStack outputs — run make eks-deploy first"; exit 1; } && \
	echo "==> Updating Infinity datasource to $$DATA_URL..." && \
	DS_PAYLOAD="{\"uid\":\"ffon28bht91c0b\",\"name\":\"Infinity\",\"type\":\"yesoreyeram-infinity-datasource\",\"access\":\"direct\",\"isDefault\":true,\"url\":\"$$DATA_URL\",\"jsonData\":{}}" && \
	EXISTING_DS=$$(curl -sf "$$GRAFANA_URL/api/datasources/name/Infinity" \
	  -H "Authorization: Bearer $$API_KEY" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "") && \
	if [ -n "$$EXISTING_DS" ]; then \
	  curl -sf -X PUT "$$GRAFANA_URL/api/datasources/$$EXISTING_DS" \
	    -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	    -d "$$DS_PAYLOAD" > /dev/null && echo "  Updated datasource (id=$$EXISTING_DS, url=$$DATA_URL)"; \
	else \
	  curl -sf -X POST "$$GRAFANA_URL/api/datasources" \
	    -H "Authorization: Bearer $$API_KEY" -H "Content-Type: application/json" \
	    -d "$$DS_PAYLOAD" > /dev/null && echo "  Created datasource (url=$$DATA_URL)"; \
	fi && \
	echo "==> Redeploying dashboards with EKS data URL..." && \
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

eks-redeploy: ## Restart pod to pick up a freshly pushed image
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	kubectl rollout restart deployment/$$APP_NAME -n $$NAMESPACE

eks-logs: ## Tail live pod logs
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	kubectl logs -f deployment/$$APP_NAME -n $$NAMESPACE

eks-exec: ## Open an interactive shell in the running pod
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	kubectl exec -it deployment/$$APP_NAME -n $$NAMESPACE -- /bin/sh

eks-full-deploy: ## End-to-end EKS deploy from scratch — idempotent, safe to re-run
	@$(MAKE) --no-print-directory eks-deploy        # CDK: cluster + EFS + IAM + AlbSg + Grafana workspace (CloudFront created with placeholder origin if eks_alb_dns is empty)
	@$(MAKE) --no-print-directory eks-kubeconfig    # configure kubectl
	@$(MAKE) --no-print-directory eks-tag-subnets   # tag public subnets for LBC
	@$(MAKE) --no-print-directory eks-lb-controller # install AWS Load Balancer Controller via Helm
	@echo "==> Waiting for LB Controller webhook to be ready..."
	@kubectl -n kube-system wait --for=condition=ready pod -l app.kubernetes.io/name=aws-load-balancer-controller --timeout=120s
	@$(MAKE) --no-print-directory eks-helm-install  # deploy app + Ingress (LBC provisions ALB)
	@$(MAKE) --no-print-directory eks-set-alb       # write ALB DNS to cdk.json
	@$(MAKE) --no-print-directory eks-deploy        # CDK again: update CloudFront origin to real ALB DNS
	@$(MAKE) --no-print-directory grafana-setup     # create/rotate Grafana API key in SSM
	@$(MAKE) --no-print-directory grafana-add-user  # assign SSO user as Grafana admin
	@$(MAKE) --no-print-directory eks-grafana-deploy # install plugin, configure datasource, push dashboards

eks-full-redeploy: ## Full EKS teardown and redeploy — safe to run unattended (nohup make eks-full-redeploy > redeploy-eks.log 2>&1 &)
	bash scripts/redeploy-eks.sh

eks-destroy: ## Tear down EKS CDK stack (helm release uninstalled first)
	@NAMESPACE=$$(jq -r '.context.eks_namespace' cdk.json) && \
	APP_NAME=$$(jq -r '.context.app_name' cdk.json) && \
	helm uninstall $$APP_NAME --namespace $$NAMESPACE || true && \
	REGION=$$(aws configure get region 2>/dev/null || aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text) && \
	ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) && \
	CDK_DEFAULT_ACCOUNT=$$ACCOUNT CDK_DEFAULT_REGION=$$REGION \
	cdk destroy NceEksStack --app "python eks_app.py" --force
