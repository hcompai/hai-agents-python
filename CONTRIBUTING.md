# Contributing

The client code under `packages/sdk/src/` is generated and should not be
hand-edited — changes there are overwritten when the SDK is next published. For
SDK behavior or API coverage, open an issue describing what you need.

Hand-written parts of this repo (tests, packaging, docs) are open to PRs. For
anything non-trivial, open an issue first.

## Dev setup

```bash
git clone https://github.com/hcompai/hai-agents-python && cd hai-agents-python
uv sync --group dev
```

## Run tests

```bash
uv run pytest packages/sdk/tests
uv run pytest packages/sdk/tests/integration -m integration -v
```
