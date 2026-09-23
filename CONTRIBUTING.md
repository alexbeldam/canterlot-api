# Contributing to Canterlot API

Thanks for considering a contribution! A few things to know before you dive in.

## Contributor License Agreement

Before any pull request can be merged, you'll need to sign our [Contributor License Agreement](CLA.md): a bot will comment on your first pull request with instructions, and signing is just a single comment reply, no paperwork. It reads more formally than it needs to, so the CLA opens with a plain-English summary of what it actually means before the legal terms, worth a skim if legal documents aren't your thing.

### Why We Require It

Canterlot is licensed under the Business Source License. The CLA gives us the ability to also offer a commercial license alongside it, on contributions old and new, without having to circle back to every contributor individually.

## Getting Started

This project uses [`uv`](https://docs.astral.sh/uv/) for Python dependency and environment management, and [`just`](https://github.com/casey/just) as the command runner, install both first (each has prebuilt binaries/install scripts for macOS, Linux, and Windows). You'll also want [Docker](https://docs.docker.com/get-docker/) running locally for the steps below. The repository includes a `docker-compose.yml` file config to back your local stack.

Once those are in place:

```bash
uv sync --dev
just setup    # creates a .env from .env.example, and spins up the MongoDB 6.0 and Redis 7.0 containers
just verify   # full lint/type/test/coverage gate
just dev      # runs the API locally with live reload, on http://localhost:8080
```

### Tooling Habits to Keep in Mind

- **Managing Dependencies:** When adding or removing packages, use `uv add <package>`, `uv add --dev <package>`, or `uv remove <package>` rather than editing `pyproject.toml`'s dependency arrays by hand. This keeps our lockfile perfectly in sync. Hand-editing tool settings blocks (like `[tool.ruff]` or `[tool.mypy]`) is totally fine.

- **Verification:** Rely on `just verify` (or its individual steps, like `just test` or `just pyright`, while iterating) for validating code, and give it a full run before calling a change done. `just ci` reproduces the exact read-only CI gate if you need to debug a failure locally.

## Architecture & Layering

The codebase follows a strict layered convention: `routers/` -> `use_cases/` -> `services/` -> `repositories/` -> `models/`. Each layer should only talk to the layer immediately below it:

- **Routers depend on services and use cases only:** Please don't import or call a repository from a router. The only approved exception is `routers/dependencies/providers.py` for FastAPI dependency-injection wiring (helpers like `get_current_user_id` or `get_club_id_from_slug`, not business endpoints).

- **Services stay independent:** Services shouldn't call sibling services. A service should only know about its own repositories.

- **Cross-service orchestration lives in `use_cases/`:** When an endpoint needs to coordinate more than one service (like creating a club and rotating its invite token), that orchestration belongs in a `use_cases/` class, not in the router or in either service. A use case's constructor takes the services it needs and exposes a single `async execute(...)`; the router depends on the use case via DI (see `routers/dependencies/providers.py`'s `get_*_use_case` factories) instead of wiring the services together itself. Endpoints that only ever need a single service can keep calling it directly from the router, a use case is for orchestration, not a mandatory wrapper around every service call.

- **Repositories own the queries:** This is the only layer that should talk to Beanie or Mongo query machinery. Services and routers shouldn't construct database queries. If you find yourself adding a repository or another service as a router's dependency, it's a great indicator that the data-shaping or orchestration belongs one layer down, into a `use_cases/` class or a repository method.

- **Single-document write vs. multi-document write:** A repository method whose write only ever needs to guard one document stays a plain CAS-style conditional filter (no session, no transaction). Once an operation has to keep more than one document consistent with each other, use a real Mongo transaction instead, via `repositories/beanie/transactions.py`'s `transactional`/`transactional_or_false`/`transactional_or_none` decorators (see `BeanieClubMembershipRepository`'s `transfer_ownership`/`reclaim_ownership` for the reference implementation). See the wiki's [Transactional Writes vs. CAS](https://github.com/alexbeldam/canterlot-api/wiki/Transactional-Writes-vs-CAS) page for the full reasoning.

### Data Boundary & Public Identifiers

- **DTO Isolation:** The `dto/` directory is the only layer allowed to cross the API boundary. Routers should return `dto/` schemas, never a raw `models/` `Document` instance.

- **No Internal ID Leaks:** Raw MongoDB `ObjectId` or `_id` keys should never show up in a request or response body. Public identifiers replace them everywhere: club `slug`, book `external_id`/ISBN, or `username`. The single exception is invites, where the public token is the shortuuid `_id` by design.

- **Keep Changes Separated:** Data model changes belong in `models/`, while API response shape adjustments belong in `dto/`. Don't reuse a database `Document` as a response schema.

## Data Modeling: Embedded vs. Extracted Relationships

Before adding a new `list[...]`/`dict[...]` field on a `Document` that references another resource, check whether it should really be embedded on the parent or pulled out into its own top-level collection instead (`ReadBookModel`/`BeanieReadBookRepository` is the reference implementation for the extracted side). See the wiki's [Embedding vs Extracting Related Data](https://github.com/alexbeldam/canterlot-api/wiki/Embedding-vs-Extracting-Related-Data) page for the full checklist.

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

- **Exploded Multi-Line Calls:** A call, `def`, or collection literal that doesn't fit on one line should have one argument/item per line with a trailing comma after the last one, not sit packed onto a single indented line. `just fmt` won't add that trailing comma retroactively on its own, so add it yourself and re-run `just fmt` when you touch a file that has this shape.

- **Structured Logging:** The `services/` and `gateways/` layers log via `structlog` (`logger = get_logger(__name__)`, then a bound `log = logger.bind(...)` per call for anything that mutates state, calls an external API, or has more than one outcome branch). Log on entry/success and on every branch that raises, and never log secrets, passwords, or tokens. See `gateways/auth/clients/google.py`'s `GoogleAuthProvider.verify()` for the reference shape.

## Tests

- **High Coverage Gate:** We hold test coverage to a strict **95% threshold evaluated per-file**, rather than an aggregate codebase average. Please ensure new code exercises actual conditional loops, error routines, and branch flows, not just the happy path.

- **Layout & Style:** Test paths mirror `src/canterlot/` hierarchy exactly. We use a `pytest-describe` style layout, grouping suites into `describe_<unit>` blocks containing `it_<behavior>` functions.

- **Environment Isolation:** Tests must never depend on your local `.env` variables. Use `monkeypatch.setattr(get_settings(), ...)` to explicitly pin configuration options both ways (set and unset) inside your test setup blocks.

- **Aggregation & Integration Tier:** `mongomock`/`mongomock-motor` cannot run `.aggregate()` at all against this codebase's async driver setup, so any repository method using `$lookup`/`$facet`/etc. is unrunnable under the default mocked fixture, not just unreliable. That's why `tests/repositories/` exists as a separate real-Mongo/real-Redis tier (via `testcontainers`, tagged `@pytest.mark.integration`): every method on every `Beanie*Repository` and `RedisCacheRepository` gets its test there, not just the aggregation-based ones, which is what lets those two directories sit in the same 95% per-file coverage gate as everything else with no exemptions.

- **Docker Setup:** Running `just test` stays entirely Docker-free (`pytest -m "not integration"`) for quick local iteration; `just test-integration` runs just the integration tier in isolation. Running `just coverage` (and therefore `just verify`/`just ci`) executes all unit and integration tests together in one `pytest --cov` run, requiring local Docker to be up and running.

- **Zero Warnings:** CI fails on any test warning. If it's coming from third-party library internals you don't control rather than your own change, don't try to work around it, add a scoped `ignore:` entry to `pyproject.toml`'s `filterwarnings` instead (see the existing entries there for the pattern).

## Local Dev Seed Data (`tools/seed/`)

Running `just seed` populates your local environment with enough clubs, users, and data to test endpoints manually without making dozens of upfront requests.

- **Full Wipe, Not Selective Cleanup:** The seeder drops every `BEANIE_DOCUMENT_MODELS` collection (via `DatabaseManager.reinitialize()` to rebuild indexes afterward) before reseeding, rather than matching and deleting previously seeded rows. This keeps `just seed` idempotent without needing to track durable identifiers across runs.

- **Builds Documents Directly:** `tools/seed/` saves models directly in whatever state they need through `tools/factories/` (`create_async`/`create_batch_async`), setting fields like `profile_completed_at` or legal-acceptance versions explicitly rather than calling into `services/` or `use_cases/`. Reaching the same state through services would take many separate calls per entity, and could trigger side effects we don't want during seeding, like sending real emails. If you add a new seeded state, set the fields it needs directly rather than reaching for a service call.

- **No Random Ghost References:** Always pass explicit `members=[...]`, `banned_users=[...]`, `pending_approvals=[...]`, a catalog entry's `club_id=...`, and similar relational fields into factory calls when a document must reference another seeded entity's real id. Polyfactory will otherwise happily generate a random, unrelated `PydanticObjectId` for any field you don't override.

- **Production Guard:** The seeder refuses to run when `environment` is `PROD`. Don't remove that guard to make a script more convenient.

- **Update It Alongside New Features:** When a new use case ships (a new endpoint, a new role, a new setting), add whatever data that use case needs to `tools/seed/` in the same change, built directly via factories per the rule above. A seed script that only covers last month's features stops being a substitute for manual setup. If you added an endpoint and can't find seed data to exercise it against, that's a sign the seed script needs an update, not a reason to seed it by hand and move on.

## Commit Messages & Git

- **Conventional Logs:** This project uses Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, optionally scoped like `feat(clubs):`). Please stick to the format, and stay consistent about which type you use for a given kind of change, since automatic release tools group commits by type to bump versions and build changelogs. Only `feat` and `fix` (plus a `BREAKING CHANGE:` footer forcing a major bump) drive actual release version updates, so reserve them for commits that actually change product behavior under `src/` rather than tooling, CI, docs, or formatting changes that would otherwise "feel like" a fix.

- **No AI Attribution:** Using AI tools to help write a contribution is fine, just leave AI co-author or `Co-Authored-By` trailers (Claude or otherwise) out of the commit message, so authorship in the log stays with you.

- **History Safety:** Never rewrite, rebase, or amend a commit block that has already been pushed to the remote repository without coordinating first. Please avoid force-pushing branches without explicit per-instance verification. Always keep local configuration utilities untracked and outside version staging.

## Pull Requests

- **Target Branch:** Always open your pull requests targeting our `develop` branch, never `main`. Use a concise branch structure: `<scope>/<short-description>` (e.g. `feat/auth`, not `feat/oauth-signup-referral-attribution`).

- **PR Description Template:** Follow the repository template at `.github/pull_request_template.md` so review context is always consistent. If you use GitHub CLI, open with: `gh pr create --base develop --fill --web`.

- **Closing Issues:** If your PR ships a use case tracked as a GitHub issue, include a closing keyword in the description (e.g. `Fixes #109`) rather than closing the issue by hand; see [Working from the Issue Tracker](#working-from-the-issue-tracker) below.

## Working from the Issue Tracker

Every use case (a user-facing flow, roughly one per endpoint or closely related group of endpoints) is tracked as its own GitHub Issue rather than as a checklist item somewhere else. A closed issue is done; an open one isn't, that's the source of truth for what's actually built versus only spec'd.

- **Labels:** Each issue carries a `domain:<name>` label (`domain:auth`, `domain:club`, `domain:catalog`, and so on), and, while open, a `status:not-started` or `status:partial` label, a `size:small`/`size:medium`/`size:large` estimate, and `blocked`/`help wanted`/`good first issue` where applicable.
- **Finding Something to Work On:** Before starting new feature work, filter open issues by a domain's `domain:<name>` label to see what's already done, partial, or not started (`gh issue list --label domain:<name> --state all` if you use GitHub CLI). `help wanted` and `good first issue` are reasonable starting points if you're new to the codebase.
- **Cross-Issue Completeness:** A use case can be internally correct and still be unbuildable from the frontend if it depends on a piece another issue was supposed to supply, most often a write path shipping with no matching read path for the client to render the new state. Re-read the issue's own body for hedges like "deferred" before treating a gap as resolved, its summary can describe something as closed while the body still says otherwise.
- **Build Leaves Before Consumers:** When a new feature depends on something unbuilt, build the dependency first even if the consumer is the more valuable feature. Shipping the consumer early without it just guarantees revisiting already-shipped code the moment the dependency lands.
- Coverage percentages and cross-cutting design rationale for each domain live in the wiki's [Progress and Roadmap](https://github.com/alexbeldam/canterlot-api/wiki/Progress-and-Roadmap) page, not on the issues themselves.

## Domain & Planning Context

- **Security Hierarchy:** Club roles rank strictly as `OWNER` > `ADMIN` > `MEMBER`. A privileged action against a member is only permitted when the caller strictly outranks the target: an `ADMIN` can never demote, remove, or ban another `ADMIN` or the `OWNER`. See the wiki's [Club Role Hierarchy](https://github.com/alexbeldam/canterlot-api/wiki/Club-Role-Hierarchy) page for the full rule, including how it interacts with ownership transfers.

## GitHub Actions Workflows

New or touched workflow steps under `.github/workflows/` should write their outcome, skip reason, or failure reason to `$GITHUB_STEP_SUMMARY` rather than only `echo`-ing to the raw log. The run overview page should explain on its own why a step did or didn't do something; see `dependabot-auto-merge.yml`, `quality.yml`, `deploy.yml`, and `release.yml` for the pattern already in use.

## Reference: The Wiki

Architecture constraints, non-functional requirements, and cross-cutting domain design decisions live in this project's [GitHub wiki](https://github.com/alexbeldam/canterlot-api/wiki), not in this file. This document covers how to contribute; the wiki covers why the rules exist and tracks what's actually built. Worth a look before starting non-trivial work, especially:

- **[Home](https://github.com/alexbeldam/canterlot-api/wiki/Home)**: the wiki's map of every page, grouped by area.
- **[Progress and Roadmap](https://github.com/alexbeldam/canterlot-api/wiki/Progress-and-Roadmap)**: what's done, partial, or not started, per domain.
- **[API Endpoint Reference](https://github.com/alexbeldam/canterlot-api/wiki/API-Endpoint-Reference)**: every implemented, documented route, grouped by resource (for full request/response schemas, use the live Swagger UI at `/docs` instead).
- **[Non-Functional Requirements](https://github.com/alexbeldam/canterlot-api/wiki/Non-Functional-Requirements)**: cross-cutting security, privacy, reliability, and performance requirements the API is held to independent of any single feature.
- **[Club Role Hierarchy](https://github.com/alexbeldam/canterlot-api/wiki/Club-Role-Hierarchy)** and **[Authorization and Resource Ownership](https://github.com/alexbeldam/canterlot-api/wiki/Authorization-and-Resource-Ownership)**: who can act on what, within a club and on a caller's own account respectively.
- **[Embedding vs Extracting Related Data](https://github.com/alexbeldam/canterlot-api/wiki/Embedding-vs-Extracting-Related-Data)** and **[Transactional Writes vs CAS](https://github.com/alexbeldam/canterlot-api/wiki/Transactional-Writes-vs-CAS)**: the two data-modeling/write-safety decisions summarized above, in full.

The wiki is a separate git repository from this one; wiki pages aren't edited as a side effect of a code pull request.
