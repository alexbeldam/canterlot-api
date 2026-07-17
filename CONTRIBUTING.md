# Contributing to Canterlot

Thanks for considering a contribution! A few things to know before you dive in.

## Contributor License Agreement

Before any pull request can be merged, you'll need to sign our [Contributor License Agreement](CLA.md). A bot will comment on your first pull request with instructions -- it's a single comment reply, no paperwork.

## Getting Started

This project uses [`uv`](https://docs.astral.sh/uv/) for Python dependency and environment management, and [`just`](https://github.com/casey/just) as the command runner -- install both first (each has prebuilt binaries/install scripts for macOS, Linux, and Windows). You'll also want [Docker](https://docs.docker.com/get-docker/) running locally for the steps below.

Once those are in place:

```bash
uv sync --dev
just setup    # creates a .env from .env.example if you don't have one yet, and starts the local Docker services
just verify   # full lint/type/test/coverage gate
```

We'd suggest running Python commands through `uv run <command>` rather than activating `.venv` directly -- it saves you from interpreter/dependency drift -- but that's a convenience recommendation, not a requirement; use whatever workflow you're comfortable with.

`just verify` runs the same checks CI does: lint, formatting, type checking (mypy and pyright), dependency-usage checks, test coverage, and complexity checks. While iterating, feel free to just run what's relevant to what you're touching (e.g. `just test`, `just pyright`) -- it's worth running `just verify` in full before opening a pull request, since that's what CI will end up checking anyway.

Part of the test suite (`tests/repositories/`) spins up real MongoDB/Redis containers via `testcontainers`, so `just verify`/`just coverage` need Docker running locally. Day-to-day unit test iteration (`just test`) does not need Docker.

## Architecture

The codebase follows a layered convention: `routers/` -> `services/` -> `repositories/` -> `models/`, where each layer generally only talks to the layer directly below it:

- Routers call into services, rather than repositories directly.
- Services generally don't call other services -- cross-service orchestration usually lives in the router, which is free to depend on multiple services.
- Repositories are where the database query code (Beanie/MongoDB) lives.

Similarly, a raw MongoDB `ObjectId`/`_id` generally shouldn't show up in a request or response body -- public identifiers (a club's `slug`, a book's `external_id`, a `username`) are used instead. Following these conventions makes for a much smoother review, since it's how the rest of the codebase is organized, but if your change has a good reason to bend a rule, explain it in the PR and we can talk it through.

## Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, optionally scoped, e.g. `feat(clubs):`). We'd really appreciate you following the convention, since releases and version bumps are generated automatically from commit history -- a commit that doesn't follow it just won't be picked up correctly by that tooling.

## Tests

- It's a big help if new code comes with tests that exercise its actual branches (including error paths), not just the happy path -- we hold coverage to 95% per file.
- Test layout mirrors `src/canterlot/`: `tests/models/`, `tests/dto/`, `tests/services/`, `tests/routers/`.
- Tests use a `pytest-describe` style: `describe_<unit>` groups containing `it_<behavior>` functions. Not a hard requirement for a contribution, but matching it keeps things consistent.

## Pull Requests

- Please open pull requests against `develop`, not `main`.
- Smaller, focused pull requests are easier for us to review than one that bundles several unrelated changes.
- Running `just verify` locally before requesting review saves a round trip if CI would've caught something.
