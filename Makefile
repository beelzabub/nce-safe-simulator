.PHONY: build data interactive static serve deploy-local redeploy deck-screenshots deck

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

## Capture sprint-review deck screenshots (Playwright, ~10-15 min). See deck/README.md.
deck-screenshots:
	python3 deck/capture_screenshots.py
	python3 deck/capture_diagrams.py
	python3 deck/capture_cli_menu.py

## Build the sprint-review .pptx from live metrics + screenshots + the SAIC template
deck:
	python3 deck/fetch_metrics.py
	python3 deck/build_deck.py
