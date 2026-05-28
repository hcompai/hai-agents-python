.PHONY: regen-sdk regen-sdk-from-main test test-unit test-integration

# Manual regen against a schema file you already have on disk.
# Usage: make regen-sdk SCHEMA=/path/to/openapi.json
SCHEMA ?= openapi.json

regen-sdk:
	@set -eu; \
	if [ ! -f "$(SCHEMA)" ]; then \
		echo "ERROR: schema file not found: $(SCHEMA)"; \
		echo "Pass SCHEMA=<path> or run 'make regen-sdk-from-main' to pull from agent_platform CI."; \
		exit 1; \
	fi; \
	echo "Regenerating SDK from $(SCHEMA)..."; \
	uv run --no-project python scripts/prepare_openapi.py \
		"$(SCHEMA)" /tmp/openapi.filtered.json; \
	rm -rf src/agent_platform/; \
	openapi-python-client generate \
		--path /tmp/openapi.filtered.json \
		--config config.yaml \
		--custom-template-path templates/ \
		--meta uv \
		--output-path src/ \
		--overwrite; \
	cp templates/__init__.py.static src/agent_platform/__init__.py; \
	if [ "$(SCHEMA)" != "openapi.json" ]; then cp "$(SCHEMA)" openapi.json; fi; \
	rm /tmp/openapi.filtered.json; \
	echo "Regenerated src/. Review and commit if changes look right."

# Pull the latest schema artifact published by agent_platform's main branch and regen.
# Requires `gh` CLI authenticated against hcompai/agent_platform (actions:read).
regen-sdk-from-main:
	@set -eu; \
	echo "Looking up latest agent_platform main schema artifact..."; \
	run_id=$$(gh run list --repo hcompai/agent_platform --branch main \
		--workflow sdk-sync-dispatch.yaml --status success --limit 1 \
		--json databaseId --jq '.[0].databaseId'); \
	if [ -z "$$run_id" ] || [ "$$run_id" = "null" ]; then \
		echo "ERROR: no successful sdk-sync-dispatch run found on agent_platform main"; \
		exit 1; \
	fi; \
	echo "Pulling openapi.json from agent_platform run $$run_id..."; \
	rm -rf /tmp/agp-schema; \
	gh run download "$$run_id" --repo hcompai/agent_platform \
		--name openapi-schema --dir /tmp/agp-schema; \
	$(MAKE) regen-sdk SCHEMA=/tmp/agp-schema/openapi.json

test: test-unit

test-unit:
	uv run pytest tests/ -m "not integration"

test-integration:
	uv run pytest tests/integration -m "integration and not slow"
