.PHONY: test test-unit test-integration

test: test-unit

test-unit:
	uv run pytest tests -m "not integration"

test-integration:
	uv run pytest tests/integration -m "integration and not slow"
