.PHONY: test test-unit test-integration

test: test-unit

test-unit:
	uv run pytest packages/sdk/tests -m "not integration"

test-integration:
	uv run pytest packages/sdk/tests/integration -m "integration and not slow"
