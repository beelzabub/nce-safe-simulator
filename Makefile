.PHONY: help build data interactive static serve deploy-local redeploy redeploy-ops app-shell dev-shell registry-push deck-screenshots deck
.DEFAULT_GOAL := help

# GitLab Container Registry path for this project (issue #244). Override to push
# elsewhere, e.g. `make registry-push REGISTRY=registry.gitlab.com/you/proj`.
REGISTRY ?= registry.gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator

# Name of the running app container (matches scripts/redeploy.sh).
APP ?= nce-safe-sim

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n"} /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

##@ Reports & site
build: data interactive static ## Full pipeline: data -> interactive -> static

data: ## Fetch report data from GitLab (NceGitLab.py --report all)
	python NceGitLab.py --report all

interactive: ## Export all Marimo WASM notebooks with a shared asset directory
	@echo "Exporting Marimo WASM notebooks..."
	python build_interactive.py

static: ## Render the Quarto static report site (quarto render)
	quarto render

serve: ## Serve the built site locally on port 4645
	python -m http.server 4645 --directory public

##@ Single-box deploy (EC2)
deploy-local: ## Bring up the box: build image, start app + Caddy (TLS)
	bash scripts/deploy-local.sh

redeploy: ## Rebuild image and hot-swap the live app container (Caddy untouched)
	bash scripts/redeploy.sh

# Ops variant bakes the CDK toolchain into the image so the in-app ECS/EKS
# Deploy/Destroy buttons work from inside the container (#231).
redeploy-ops: ## redeploy, but with the ops image variant (CDK toolchain baked in)
	bash scripts/redeploy.sh --ops

app-shell: ## Bash shell inside the running app container (APP=nce-safe-sim)
	docker exec -it $(APP) bash

##@ Vendored dependency closures (issues #269/#271/#296)
# The developer loop for dependency changes: edit the input, run the matching
# target, commit the lock diff, push. pip/npm registry versions are derived
# from the lock files' own sha256 (no version to bump); the capture must be
# published BEFORE the push, or the MR pipeline's image build 404s — which is
# the drift guard. See scripts/capture-deps.sh for the details.
capture-deps: ## Refresh pip+npm vendored closures (recompile lock, publish if new) — run BEFORE pushing
	bash scripts/capture-deps.sh all

capture-pip: ## Recompile requirements.lock + publish its wheel closure if new
	bash scripts/capture-deps.sh pip

capture-npm: ## Publish the npm cache for frontend/package-lock.json if new
	bash scripts/capture-deps.sh npm

capture-apt: ## Re-capture the apt-debs closure (dated), print the Dockerfile values to set
	bash scripts/capture-deps.sh apt

##@ Container image / dev
# Builds the dev/build image and drops into a shell with the working tree mounted
# at /app — full toolchain, nothing installed on the host. Host :4645 maps to the
# app's container :8080 (`--serve` binds :8080), reachable at http://localhost:4645.
# While dependencies are churning, `make dev-shell OFFLINE=0` installs pip/npm
# from the internet (still lock-pinned) instead of the vendored registry
# packages — capture + version-bump once, before merging (issue #271).
OFFLINE ?= 1
dev-shell: ## Container dev shell: dev image + working tree mounted at /app
	docker build --target dev \
	  --build-arg PKG_PROJECT=$$(scripts/pkg-project-url.sh) \
	  --build-arg OFFLINE=$(OFFLINE) \
	  -t nce-safe-simulator:dev .
	docker run --rm -it -v "$$PWD":/app -w /app -p 4645:8080 nce-safe-simulator:dev

# Local/manual mirror of the CI `containerize` job (#244). Log in first:
# `docker login registry.gitlab.com` (username + a PAT/deploy token with
# read_registry+write_registry scope).
registry-push: ## Build + push runtime + dev images to the GitLab Container Registry
	@REF=$$(git rev-parse --short HEAD); \
	VER=$$(git describe --tags --exact-match 2>/dev/null || true); \
	docker build --target runtime \
	  --build-arg VCS_REF=$$REF --build-arg NCE_VERSION=$$VER \
	  --build-arg PKG_PROJECT=$$(scripts/pkg-project-url.sh) \
	  -t $(REGISTRY):latest -t $(REGISTRY):$$REF . && \
	docker build --target dev \
	  --build-arg PKG_PROJECT=$$(scripts/pkg-project-url.sh) \
	  -t $(REGISTRY)/dev:latest -t $(REGISTRY)/dev:$$REF . && \
	docker push $(REGISTRY):latest && docker push $(REGISTRY):$$REF && \
	docker push $(REGISTRY)/dev:latest && docker push $(REGISTRY)/dev:$$REF && \
	echo "Pushed runtime ($(REGISTRY):latest,$$REF) + dev ($(REGISTRY)/dev:latest,$$REF)"

##@ Status deck
deck-screenshots: ## Capture sprint-review deck screenshots (Playwright, ~10-15 min)
	python3 deck/capture_screenshots.py
	python3 deck/capture_diagrams.py
	python3 deck/capture_cli_menu.py
	python3 deck/capture_test_log.py
	python3 deck/capture_git_workflow.py
	python3 deck/capture_ci_router.py

deck: ## Build the sprint-review .pptx from live metrics + screenshots + template
	python3 deck/fetch_metrics.py
	python3 deck/build_deck.py
