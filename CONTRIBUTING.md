# Contributing

This repository is an **output-only mirror**. The Python SDK under
`packages/sdk/src/agent_platform/` is generated from
[hcompai/agent_platform](https://github.com/hcompai/agent_platform)'s OpenAPI
schema and synced here by an automated PR. The codegen toolchain (generator,
templates, config, version policy) lives upstream in `agent_platform`.

**Do not hand-edit anything under `packages/sdk/src/`.** The next sync PR will
overwrite it. To change the SDK:

| You want to change... | Where to make the change |
| --- | --- |
| A model field, an endpoint, or which endpoints the SDK exposes | The API in [`hcompai/agent_platform`](https://github.com/hcompai/agent_platform) |
| The generator config, templates, or version policy | `sdk-codegen/` in [`hcompai/agent_platform`](https://github.com/hcompai/agent_platform) |

Hand-written parts of this repo (tests, packaging, docs) are open to PRs. For
anything non-trivial, open an issue first.

## Dev setup

```bash
git clone https://github.com/hcompai/hai-agents-python && cd hai-agents-python
uv sync --group dev
```

## Run tests

```bash
uv run pytest packages/sdk/tests                                 # unit (integration deselected)
uv run pytest packages/sdk/tests/integration -m integration -v    # live API (needs HAI_API_KEY_TEST)
```
