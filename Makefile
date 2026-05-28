.PHONY: regen-sdk test test-unit test-integration

OPENAPI_URL ?= https://agp.hcompany.ai/openapi.json

regen-sdk:
	@set -eu; \
	echo "Fetching live OpenAPI schema from $(OPENAPI_URL)..."; \
	curl --fail --silent --show-error "$(OPENAPI_URL)" -o /tmp/openapi.json; \
	cd python; \
	uv run --no-project --with pyyaml python scripts/filter_openapi.py \
		/tmp/openapi.json filter.yaml /tmp/openapi.filtered.json; \
	rm -rf src/agent_platform/; \
	openapi-python-client generate \
		--path /tmp/openapi.filtered.json \
		--config config.yaml \
		--custom-template-path templates/ \
		--meta uv \
		--output-path src/ \
		--overwrite; \
	cp templates/__init__.py.static src/agent_platform/__init__.py; \
	cp /tmp/openapi.json ../openapi.json; \
	rm /tmp/openapi.json /tmp/openapi.filtered.json; \
	echo "Regenerated python/src/. Review and commit if changes look right."

test: test-unit

test-unit:
	cd python && uv run pytest tests/ -m "not integration"

test-integration:
	cd python && uv run pytest tests/integration -m "integration and not slow"
