# System packages come from this project's generic package registry, not
# deb.debian.org / deb.nodesource.com (issue #269): package `apt-debs` holds
# per-layer, per-arch .deb closures captured by scripts/capture-apt-debs.sh;
# each layer below fetches its manifest via scripts/fetch-apt-debs.py and
# installs with an OFFLINE `apt-get install /tmp/debs/*.deb` (apt orders
# Pre-Depends that a flat dpkg -i cannot; with no apt indexes in the slim
# image it cannot reach a mirror — an incomplete closure fails loudly).
# PKG_PROJECT (no default — see the runtime stage note) names the GitLab
# project; APT_DEBS_VERSION pins the captured set.
ARG PKG_PROJECT
ARG APT_DEBS_VERSION=2026.07.22

# Stage 1 — build the Vue frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — architecture diagram builder (Python diagrams library + graphviz)
FROM python:3.11-slim AS diagram-builder
COPY scripts/fetch-apt-debs.py /usr/local/bin/fetch-apt-debs.py
ARG PKG_PROJECT
ARG APT_DEBS_VERSION
RUN test -n "$PKG_PROJECT" || { \
      echo "ERROR: PKG_PROJECT build-arg is required (no default — issues #262/#269)." >&2; \
      echo "  Use the make targets / scripts (they derive it from git remote origin)," >&2; \
      echo "  or pass: --build-arg PKG_PROJECT=https://<gitlab-host>/api/v4/projects/<id>" >&2; \
      exit 1; } && \
    python3 /usr/local/bin/fetch-apt-debs.py "$PKG_PROJECT" "$APT_DEBS_VERSION" \
      graphviz "$(dpkg --print-architecture)" /tmp/debs && \
    apt-get install -y --no-install-recommends /tmp/debs/*.deb && rm -rf /tmp/debs
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

# Install Quarto (required for plotly/static site build format). The pinned
# .deb (both arches) is vendored in the project's generic package registry
# (package `quarto`, issue #262) rather than fetched from GitHub releases, so
# image builds work on networks without GitHub egress. The registry allows
# anonymous pull (package_registry_access_level=public) — no token in the
# build, none can leak into image history. Downloaded with stdlib urllib —
# installing curl first would be exactly the apt egress #269 removes.
#
# PKG_PROJECT has NO default on purpose: a hardcoded host would silently
# point at the wrong network after an enclave lift. Every make target /
# script derives it from the clone's own `git remote origin` via
# scripts/pkg-project-url.sh, and CI passes its own instance — a bare
# `docker build .` without the arg fails loudly instead:
#   --build-arg PKG_PROJECT=https://<gitlab-host>/api/v4/projects/<id-or-url-encoded-path>
COPY scripts/fetch-apt-debs.py /usr/local/bin/fetch-apt-debs.py
ARG QUARTO_VERSION=1.9.38
ARG PKG_PROJECT
ARG APT_DEBS_VERSION
RUN test -n "$PKG_PROJECT" || { \
      echo "ERROR: PKG_PROJECT build-arg is required (no default — issues #262/#269)." >&2; \
      echo "  Use the make targets / scripts (they derive it from git remote origin)," >&2; \
      echo "  or pass: --build-arg PKG_PROJECT=https://<gitlab-host>/api/v4/projects/<id>" >&2; \
      exit 1; } && \
    ARCH=$(dpkg --print-architecture) && \
    python3 -c 'import sys, urllib.request as u; u.urlretrieve(sys.argv[1], sys.argv[2])' \
      "${PKG_PROJECT}/packages/generic/quarto/${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${ARCH}.deb" \
      /tmp/quarto.deb && \
    dpkg -i /tmp/quarto.deb && \
    rm /tmp/quarto.deb

# WeasyPrint (epic-cards PDF export, #249) is a wrapper around Pango; the pip
# package cannot render without these system libraries + a font. graphviz above
# covers the diagrams library — this covers the PDF renderer. The closure comes
# from the apt-debs package (issue #269), not deb.debian.org — it is the slim
# image's superset of the 3-deb `weasyprint-apt-debs` set the CI test job uses
# (the full python:3.11 test image already carries the transitive libs).
RUN python3 /usr/local/bin/fetch-apt-debs.py "$PKG_PROJECT" "$APT_DEBS_VERSION" \
      weasyprint "$(dpkg --print-architecture)" /tmp/debs && \
    apt-get install -y --no-install-recommends /tmp/debs/*.deb && rm -rf /tmp/debs

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
# NOTE: ops is deliberately outside the enclave/air-gap scope of issue #269 —
# it is never built in CI, and its toolchain (AWS CLI, cdk, nodesource, docker
# static binary) exists to drive AWS deploys, which no enclave build performs.
# Its layers still reach the public internet; build it only on open networks.
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

# docker CLI (client only, static binary) — the first-time ECS deploy builds
# and pushes the initial image (the make target's empty-repo branch: deploy
# scaled to 0, push, scale up). No daemon ships in the image; the run scripts
# mount the host's /var/run/docker.sock for the --ops variants.
ARG DOCKER_CLI_VERSION=27.5.1
RUN ARCH=$(uname -m) \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${ARCH}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

# Python deps for the CDK apps under cdk/ (aws-cdk-lib, constructs, kubectl layer)
RUN pip install --no-cache-dir -r cdk/requirements.txt

# Stage 5 — dev/build container (issue #244): the golden toolchain image a
# developer pulls, then volume-mounts their working tree into /app to run the
# whole pipeline (make build, pytest, npm run build, quarto render, diagram
# gen) with zero local toolchain. Source is NOT baked in — it is mounted at
# run time (`make dev-shell`, or `docker run -v "$PWD":/app ...`), so the image
# stays reusable across every checkout. CI pushes it to the GitLab registry as
# .../nce-safe-simulator/dev on merges to develop. Built explicitly:
#   docker build --target dev -t nce-safe-simulator:dev .
FROM runtime AS dev

# The runtime base already carries Python 3.11 + requirements.txt (incl. pytest,
# diagrams) and the pinned Quarto CLI. The dev image adds the rest of the build
# toolchain: Node 20 (matches the frontend-builder stage) for `npm ci && npm run
# build`, graphviz for the `diagrams` library's `dot`, and make/git/jq/curl for
# the everyday loop. The closure — including the NodeSource nodejs .deb — comes
# from the apt-debs package (issue #269): no deb.debian.org, no
# deb.nodesource.com setup script, and gnupg (only ever needed to install the
# NodeSource signing key) drops out entirely.
ARG PKG_PROJECT
ARG APT_DEBS_VERSION
RUN python3 /usr/local/bin/fetch-apt-debs.py "$PKG_PROJECT" "$APT_DEBS_VERSION" \
      dev "$(dpkg --print-architecture)" /tmp/debs && \
    apt-get install -y --no-install-recommends /tmp/debs/*.deb && rm -rf /tmp/debs

# Working tree is bind-mounted here at run time; drop to an interactive shell
# instead of the runtime's `--serve` entrypoint.
WORKDIR /app
ENTRYPOINT []
CMD ["bash"]

# Final stage — re-select the slim runtime so a plain `docker build .` (all
# existing call sites: cdk/Makefile ecr-push/ecs-deploy, redeploy scripts)
# still produces the slim image. BuildKit skips the unreferenced ops/dev stages.
FROM runtime
