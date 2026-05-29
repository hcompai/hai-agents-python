# Contributing

Bug reports, feature ideas, and PRs are welcome. For anything non-trivial,
open an issue first so we can sanity-check the direction before you sink time
into it.

## The SDK is auto-generated

The Python source under `packages/sdk/src/agent_platform/` is regenerated from
`openapi.json` (the schema published by [hcompai/agent_platform](https://github.com/hcompai/agent_platform))
by [`openapi-python-client==0.28.3`](https://github.com/openapi-generators/openapi-python-client).

**Do not hand-edit anything under `packages/sdk/src/`.** A sync PR will overwrite
your changes the next time the upstream schema moves. If you need to change client
behavior:

| You want to change... | Edit... |
| --- | --- |
| The exposed entrypoint (`Client`, `AsyncClient`, top-level imports) | `templates/__init__.py.static` |
| The codegen config (project name, model naming, post-hooks) | `config.yaml` |
| Which endpoints the SDK exposes, or a model field/endpoint shape | Upstream: open a PR on `hcompai/agent_platform` |

## Dev setup

```bash
git clone https://github.com/hcompai/hai-agents-python && cd hai-agents-python
uv sync --group dev
```

## Regenerate locally

```bash
make regen-sdk-from-main   # pulls the latest schema artifact from agent_platform CI
# or
make regen-sdk SCHEMA=/path/to/openapi.json
```

`packages/sdk/src/` is generated but committed: each automated sync PR commits
the regenerated code so reviewers see the diff. The initial code lands via the
first sync PR after this repo is bootstrapped. CI regenerates it from
`openapi.json` on every PR, so the test job always exercises a fresh build.

## Run tests

```bash
uv run pytest packages/sdk/tests                                  # unit (default; integration deselected)
uv run pytest packages/sdk/tests/integration -m integration -v     # live API (needs HAI_API_KEY_TEST)
```

## Pull request checklist

- [ ] If you changed `templates/` or `config.yaml`, re-run `make regen-sdk`
      and confirm the resulting diff is what you intended.
- [ ] `uv run pytest packages/sdk/tests -m "not integration"` passes locally.
- [ ] No CodeArtifact URLs slipped into `uv.lock` (the
      `Check uv.lock for private CodeArtifact references` CI guard will catch
      this, but it's faster to notice locally).
