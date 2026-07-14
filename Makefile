.PHONY: build data interactive static serve deploy-local redeploy redeploy-ops dev-shell registry-push deck-screenshots deck

## GitLab Container Registry path for this project (issue #244). Override to push
## elsewhere, e.g. `make registry-push REGISTRY=registry.gitlab.com/you/proj`.
REGISTRY ?= registry.gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator

## Run the full pipeline: fetch data, export notebooks, render static site
build: data interactive static

## Fetch report data from GitLab
data:
	python NceGitLab.py --report all

## Export all Marimo WASM notebooks with a shared asset directory
interactive:
	@echo "Exporting Marimo WASM notebooks..."
	python build_interactive.py

## Render Quarto static pages
static:
	quarto render

## Serve the built site locally on port 4645
serve:
	python -m http.server 4645 --directory public

## Single-box bring-up: build image, start app + Caddy (TLS) on nce-safe-sim.com
deploy-local:
	bash scripts/deploy-local.sh

## Iterative redeploy: rebuild image and swap the live app container (Caddy untouched)
redeploy:
	bash scripts/redeploy.sh

## Same swap, but with the ops image variant (CDK toolchain baked in) so the
## in-app ECS/EKS Deploy/Destroy buttons work from inside the container (#231)
redeploy-ops:
	bash scripts/redeploy.sh --ops

## Container-based development (issue #244): build the dev/build image and drop
## into a shell with the working tree mounted at /app — full toolchain, nothing
## installed on the host. The app port (4645) is published so `--serve` from
## inside the container is reachable at http://localhost:4645.
dev-shell:
	docker build --target dev -t nce-safe-simulator:dev .
	docker run --rm -it -v "$$PWD":/app -w /app -p 4645:4645 nce-safe-simulator:dev

## Build and push the runtime + dev images to the GitLab Container Registry
## (issue #244) — the local/manual mirror of the CI `containerize` job, for
## ad-hoc pushes. Log in first: `docker login registry.gitlab.com` (username +
## a PAT/deploy token with read_registry+write_registry scope).
registry-push:
	@REF=$$(git rev-parse --short HEAD); \
	VER=$$(git describe --tags --exact-match 2>/dev/null || true); \
	docker build --target runtime \
	  --build-arg VCS_REF=$$REF --build-arg NCE_VERSION=$$VER \
	  -t $(REGISTRY):latest -t $(REGISTRY):$$REF . && \
	docker build --target dev \
	  -t $(REGISTRY)/dev:latest -t $(REGISTRY)/dev:$$REF . && \
	docker push $(REGISTRY):latest && docker push $(REGISTRY):$$REF && \
	docker push $(REGISTRY)/dev:latest && docker push $(REGISTRY)/dev:$$REF && \
	echo "Pushed runtime ($(REGISTRY):latest,$$REF) + dev ($(REGISTRY)/dev:latest,$$REF)"

## Capture sprint-review deck screenshots (Playwright, ~10-15 min). See deck/README.md.
deck-screenshots:
	python3 deck/capture_screenshots.py
	python3 deck/capture_diagrams.py
	python3 deck/capture_cli_menu.py
	python3 deck/capture_test_log.py
	python3 deck/capture_git_workflow.py

## Build the sprint-review .pptx from live metrics + screenshots + the SAIC template
deck:
	python3 deck/fetch_metrics.py
	python3 deck/build_deck.py
