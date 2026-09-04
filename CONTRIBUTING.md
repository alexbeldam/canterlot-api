# Contributing to Canterlot API

Thanks for considering a contribution! A few things to know before you dive in.

## Contributor License Agreement

Before any pull request can be merged, you'll need to sign our [Contributor License Agreement](CLA.md) -- a bot will comment on your first pull request with instructions, and signing is just a single comment reply, no paperwork. It reads more formally than it needs to, so the CLA opens with a plain-English summary of what it actually means before the legal terms -- worth a skim if legal documents aren't your thing.

### Why We Require It

Canterlot is licensed under the Business Source License. The CLA gives us the ability to also offer a commercial license alongside it, on contributions old and new, without having to circle back to every contributor individually.

## Getting Started

This project uses [`uv`](https://docs.astral.sh/uv/) for Python dependency and environment management, and [`just`](https://github.com/casey/just) as the command runner -- install both first (each has prebuilt binaries/install scripts for macOS, Linux, and Windows). You'll also want [Docker](https://docs.docker.com/get-docker/) running locally for the steps below. The repository includes a `docker-compose.yml` file config to back your local stack.

Once those are in place:

```bash
uv sync --dev
just setup    # creates a .env from .env.example, and spins up the MongoDB 6.0 and Redis 7.0 containers
just verify   # full lint/type/test/coverage gate
```

### Tooling Habits to Keep in Mind

- **Managing Dependencies:** When adding or removing packages, use `uv add <package>`, `uv add --dev <package>`, or `uv remove <package>` rather than editing `pyproject.toml`'s dependency arrays by hand. This keeps our lockfile perfectly in sync. Hand-editing tool settings blocks (like `[tool.ruff]` or `[tool.mypy]`) is totally fine.

- **Verification:** Rely on `just verify` (or its individual steps) for validating code. It runs `just lint-fix`, `just fmt`, `just compile`, `just check-imports`, `just deptry`, `just lint`, `just mypy`, `just pyright`, `just coverage`, `just radon`, and `just xenon` in order. While iterating, feel free to run just what's relevant to your changes (`just test`, `just pyright`), but give `just verify` a full run before calling a change done. You can use `just ci` if you ever need to reproduce the exact read-only local gate to debug a CI failure.

## Architecture & Layering

The codebase follows a strict layered convention: `routers/` -> `services/` -> `repositories/` -> `models/`. Each layer should only talk to the layer immediately below it:

- **Routers depend on services only:** Please don't import or call a repository from a router. The only approved exception is `routers/dependencies.py` for FastAPI dependency-injection wiring.

- **Services stay independent:** Services shouldn't call sibling services. A service should only know about its own repositories.

- **Cross-service orchestration lives in `use_cases/`:** When an endpoint needs to coordinate more than one service (like creating a club and rotating its invite token), that orchestration belongs in a `use_cases/` class, not in the router or in either service. A use case's constructor takes the services it needs and exposes a single `async execute(...)`; the router depends on the use case via DI (see `routers/dependencies/providers.py`'s `get_*_use_case` factories) instead of wiring the services together itself. Endpoints that only ever need a single service can keep calling it directly from the router, a use case is for orchestration, not a mandatory wrapper around every service call.

- **Repositories own the queries:** This is the only layer that should talk to Beanie or Mongo query machinery. Services and routers shouldn't construct database queries. If you find yourself adding a repository as a router dependency, it's a great indicator that the data-shaping or orchestration belongs one layer down.

### Data Boundary & Public Identifiers

- **DTO Isolation:** The `dto/` directory is the only layer allowed to cross the API boundary. Routers should return `dto/` schemas, never a raw `models/` `Document` instance.

- **No Internal ID Leaks:** Raw MongoDB `ObjectId` or `_id` keys should never show up in a request or response body. Public identifiers replace them everywhere: club `slug`, book `external_id`/ISBN, or `username`. The single exception is invites, where the public token is the shortuuid `_id` by design.

- **Keep Changes Separated:** Data model changes belong in `models/`, while API response shape adjustments belong in `dto/`. Don't reuse a database `Document` as a response schema.

## RESTful API Standards

The API follows a cohesive, highly consistent set of design choices. Please apply these rules to any new or touched endpoints:

- **Paths are nouns, not verbs:** A state transition on an existing resource is a `PATCH`/`DELETE`/`PUT` on that resource's own path, never a `POST .../verb` suffix (e.g., use HTTP verbs instead of trailing actions like `/approve` or `/transfer-ownership`). If an action doesn't cleanly map to a noun, model it as its own distinct resource path (e.g., `POST /clubs/{slug}/ownership-transfers`).

- **Status codes carry the outcome:** If a caller needs to branch on what happened, that should be visible in the HTTP status code, not buried in a status/outcome enum inside an otherwise `200 OK` body. Distinguishable results get distinguishable codes (like `200` vs `201`). Non-2xx outcomes should raise a structured `BusinessError` rather than inventing a parallel body shape.

- **`201 Created` sets `Location`:** Every endpoint that creates a resource should return the new asset's canonical URL in the `Location` header, matching our `/api/v1/...` prefix.

- **No bare-scalar responses:** Even if a response is conceptually just a string or number, please wrap it in a named `dto/` schema rather than returning a raw primitive type.

- **Collection discrimination over parallel endpoints:** When two operations create a similar resource type with different input layouts, map them to a single collection `POST` endpoint using a discriminating field in the body (like `type: PUBLIC | DIRECT`). Cross-field constraints can be verified via a Pydantic `model_validator(mode="after")` on the request DTO.

- **Isolate inputs cleanly:** Path variables identify the resource being acted on, request bodies carry the mutations, and query parameters carry filters, weights, or pagination. Try not to split a single logical input concept across multiple layers.

- **Document OpenAPI content:** Every OpenAPI `responses={}` entry (excluding automatic `422` validation dumps) needs an explicit `"content": error_example(...)` block so its shape is properly documented.

- **Explicit Operation IDs:** Every endpoint route handler needs an explicit, camelCase `operation_id` that matches the Python function name verbatim (e.g., `create_club` → `operation_id="createClub"`). Our frontend code generation depends directly on this mapping.

## Database Fetching & Projections

- **Single Field -> Project:** If a caller only reads one single field off a document, add or reuse a narrow projection model (like `IdProjection` or `UsernameProjection`) instead of pulling the whole `Document` across the database wire.

- **Two or More Fields -> Fetch All:** Past one field, it's cleaner to fetch the whole entity rather than making multiple projection calls or expanding complex shapes.

- **No Resolve-Then-Refetch:** If turning identifier A into id B is just a stepping stone to immediately fetching the entity by B, add a repository method that goes straight from A to your destination value in one database trip.

- **Named Projection Models:** Every projection needs its own named model subclassing `BaseModel`, colocated with the repository using it. Avoid inline, ad-hoc `.project(dict)` variations.

- **Beanie ID Mapping:** When mapping a document's internal ID via a projection model, make sure to explicitly assign the MongoDB alias: `id: PydanticObjectId = Field(alias="_id")` paired with `model_config = ConfigDict(populate_by_name=True)`, otherwise Beanie's query pipeline will return a missing field validation error.

## Python Style & Logging

- **Self-Documenting Code:** We prefer clean, SOLID, and DRY code over narrative inline comments or multi-paragraph docstrings. Add a comment only when capturing a non-obvious _why_ (like a hidden structural constraint or upstream library workaround).

- **Complex Signatures:** Avoid returning naked tuples or loose dictionaries when a parameter or return value carries more than one explicit piece of meaning. Wrap them in a small named type, dataclass, or Pydantic model to retain type-checking precision.

- **No Assertions in Source:** Please never use `assert` statements outside of the `tests/` directory. It can be stripped entirely in optimized runtime execution modes. For real runtime invariants, use explicit conditional `raise` blocks; for pure type-checker narrowing, rely on `typing.cast`.

- **Structured Logging:** The `services/` and `providers/` layers use `structlog` via `utils.get_logger(__name__)`. Methods that mutate state, call external APIs, or contain multiple branch options should initialize a bound logger (`log = logger.bind(...)`).

- **Log All Exit Paths:** If a method leverages a bound logger, make sure _every single branch that exits by raising an exception logs before raising_ so our tracing captures it. Never log secrets, credentials, or raw tokens—log derived, non-sensitive context references instead.

## Tests

- **High Coverage Gate:** We hold test coverage to a strict **95% threshold evaluated per-file**, rather than an aggregate codebase average. Please ensure new code exercises actual conditional loops, error routines, and branch flows, not just the happy path.

- **Layout & Style:** Test paths mirror `src/canterlot/` hierarchy exactly. We use a `pytest-describe` style layout, grouping suites into `describe_<unit>` blocks containing `it_<behavior>` functions.

- **Environment Isolation:** Tests must never depend on your local `.env` variables. Use `monkeypatch.setattr(get_settings(), ...)` to explicitly pin configuration options both ways (set and unset) inside your test setup blocks.

- **Aggregation & Integration Tier:** MongoDB `.aggregate()` chains natively crash against `mongomock`. Any repository method implementing aggregation steps belongs in `tests/repositories/` and should be tagged with the `@pytest.mark.integration` marker, where real Mongo/Redis Docker containers are spun up via `testcontainers`.

- **Docker Setup:** Running `just test` stays entirely Docker-free for quick local iteration. Running `just coverage` (and therefore `just verify`) executes all unit and integration tests together, requiring local Docker to be up and running.

- **Zero Warnings:** All test runs should pass with completely zero warnings in their output. If an alert is triggered by third-party library internals we don't control, intercept it cleanly by adding a highly scoped message filter inside `pyproject.toml`'s `filterwarnings` section.

## Local Dev Seed Data (`tools/seed/`)

Running `just seed` populates your local environment with enough clubs, users, and data to test endpoints manually without making dozens of upfront requests.

- **Full Wipe, Not Selective Cleanup:** The seeder drops every `BEANIE_DOCUMENT_MODELS` collection (via `DatabaseManager.reinitialize_beanie()` to rebuild indexes afterward) before reseeding, rather than matching and deleting previously seeded rows. This keeps `just seed` idempotent without needing to track durable identifiers across runs.

- **Builds Documents Directly:** `tools/seed/` saves models directly in whatever state they need through `tools/factories/` (`create_async`/`create_batch_async`), setting fields like `profile_completed_at` or legal-acceptance versions explicitly rather than calling into `services/` or `use_cases/`. Reaching the same state through services would take many separate calls per entity, and could trigger side effects we don't want during seeding, like sending real emails. If you add a new seeded state, set the fields it needs directly rather than reaching for a service call.

- **No Random Ghost References:** Always pass explicit `members=[...]`, `banned_users=[...]`, `pending_approvals=[...]`, `catalog=[...]`, and similar relational fields into factory calls when a document must reference another seeded entity's real id. Polyfactory will otherwise happily generate a random, unrelated `PydanticObjectId` for any field you don't override.

## Commit Messages & Git

- **Conventional Logs:** This project uses Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`). Please stick to the format, as automatic release tools evaluate your messages to bump versions and build changelogs. Only `feat` and `fix` tokens (plus `BREAKING CHANGE:` footers) drive actual release version updates.

- **No AI Attribution:** Using AI tools to help write a contribution is fine, just leave AI co-author or `Co-Authored-By` trailers (Claude or otherwise) out of the commit message, so authorship in the log stays with you.

- **History Safety:** Never rewrite, rebase, or amend a commit block that has already been pushed to the remote repository without coordinating first. Please avoid force-pushing branches without explicit per-instance verification. Always keep local configuration utilities untracked and outside version staging.

## Pull Requests

- **Target Branch:** Always open your pull requests targeting our `develop` branch, never `main`. Use a concise branch structure: `<scope>/<short-description>`.

- **Scope Size:** Keeping pull requests small and tightly focused around a single concept makes manual review incredibly fast.

- **PR Description Template:** Follow the repository template at `.github/pull_request_template.md` so review context is always consistent. If you use GitHub CLI, open with: `gh pr create --base develop --fill --web`.

## Domain & Planning Context

- **Security Hierarchy:** Domain validation ranks strictly as `OWNER` > `ADMIN` > `MEMBER`. Actions require a caller to strictly outrank the target actor (an `ADMIN` cannot modify another `ADMIN` or the `OWNER`).

- **Feature Traceability:** When engineering a write execution endpoint, always trace it against a corresponding read mechanism so the frontend client has a natural way to fetch and render the new state.
