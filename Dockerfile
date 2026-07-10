# Stage 1 — build the Vue frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — architecture diagram builder (Python diagrams library + graphviz)
FROM python:3.11-slim AS diagram-builder
RUN apt-get update && apt-get install -y --no-install-recommends graphviz \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir diagrams
WORKDIR /build
COPY diagrams/ ./
RUN mkdir -p /diagrams \
    && python3 eks_architecture.py /diagrams/eks-architecture.png \
    && python3 ecs_architecture.py /diagrams/ecs-architecture.png \
    && python3 ov1_operational_concept.py /diagrams/ov1-architecture.png \
    && python3 sv1_system_interfaces.py /diagrams/sv1-architecture.png \
    && python3 sv2_deployment_eks.py /diagrams/sv2-eks-architecture.png \
    && python3 sv2_deployment_ecs.py /diagrams/sv2-ecs-architecture.png \
    && python3 dataflow_architecture.py /diagrams/dataflow-architecture.png \
    && python3 devsecops_pipeline.py /diagrams/devsecops-architecture.png

# Stage 3 — runtime image (slim; the default build and the image pushed to ECR)
FROM python:3.11-slim AS runtime
WORKDIR /app

# Install Quarto (required for plotly/static site build format)
ARG QUARTO_VERSION=1.9.38
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${ARCH}.deb" \
         -o /tmp/quarto.deb && \
    dpkg -i /tmp/quarto.deb && \
    rm /tmp/quarto.deb && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Version stamp (issue #173): the runtime container has no .git, so the
# build injects it. NCE_VERSION carries an exact tag (release build); else
# VCS_REF yields nce-<commit>. With neither, runtime falls back to VERSION.
ARG VCS_REF=""
ARG NCE_VERSION=""
RUN python3 -c "import json, os; v = os.environ.get('NCE_VERSION') or ('nce-' + os.environ['VCS_REF'] if os.environ.get('VCS_REF') else ''); open('version.json', 'w').write(json.dumps({'version': v, 'commit': os.environ.get('VCS_REF', '')})) if v else None" \
    && (cat version.json 2>/dev/null || echo "no version baked — runtime fallback")

# Overlay the pre-built frontend from Stage 1 (vite outDir is ../public/app)
COPY --from=frontend-builder /app/public/app ./public/app

# Architecture diagrams generated at build time (absent if tree.json was unavailable)
COPY --from=diagram-builder /diagrams/ ./public/architecture/

# config.json and reports/ are provided at runtime via volume mounts:
#   -v /path/to/config.json:/app/config.json:ro
#   -v /efs/nce-reports:/app/reports

EXPOSE 80

ENTRYPOINT ["python", "NceGitLab.py", "--serve"]

# Stage 4 — ops variant (issue #231): runtime + the CDK deploy toolchain, so a
# container run on an operator box (host ~/.aws mounted) can drive the in-app
# ECS/EKS deploys, which shell to `make -C cdk ...`. Built only explicitly:
#   docker build --target ops -t nce-safe-simulator:ops .
# Never pushed to ECR — the trailing default stage keeps plain builds slim.
FROM runtime AS ops

# make + jq (cdk Makefile), Node 22 LTS (nodesource; bookworm's node is too
# old for the cdk CLI, and Node 20 is EOL — jsii spams a deprecation banner
# into every deploy log), and the cdk CLI itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
        make jq curl unzip ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g aws-cdk \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 (the Makefile shells to `aws`; boto3 alone doesn't cover it)
RUN ARCH=$(uname -m) \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip

# kubectl + helm — the EKS path only (LB controller + app chart installs)
RUN ARCH=$(dpkg --print-architecture) \
    && KVER=$(curl -fsSL https://dl.k8s.io/release/stable.txt) \
    && curl -fsSL "https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH}/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Python deps for the CDK apps under cdk/ (aws-cdk-lib, constructs, kubectl layer)
RUN pip install --no-cache-dir -r cdk/requirements.txt

# Final stage — re-select the slim runtime so a plain `docker build .` (all
# existing call sites: cdk/Makefile ecr-push/ecs-deploy, redeploy scripts)
# still produces the slim image. BuildKit skips the unreferenced ops stage.
FROM runtime
