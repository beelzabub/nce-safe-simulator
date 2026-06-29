.PHONY: build data interactive static serve serve-tls

# TLS material for `serve-tls` (override on the command line as needed).
CERT      ?= certs/server.crt
KEY       ?= certs/server.key
TLS_HOSTS ?=

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

## Serve the app over HTTPS with a self-signed cert (generates one if missing).
## Bind port comes from config.json defaults.serve.port; SAN hosts: make serve-tls TLS_HOSTS="host 1.2.3.4"
serve-tls:
	@test -f $(CERT) -a -f $(KEY) || scripts/gen-selfsigned-cert.sh $(TLS_HOSTS)
	SERVE_TLS=1 SERVE_TLS_CERTFILE=$(CERT) SERVE_TLS_KEYFILE=$(KEY) python NceGitLab.py --serve
