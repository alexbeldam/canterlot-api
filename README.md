<p align="center">
  <img src="src/canterlot/static/favicon.svg" width="100" alt="Canterlot Logo">
</p>

<h1 align="center"><strong>Canterlot API 🌙</strong></h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/uv-F15A24?style=for-the-badge&logo=rust&logoColor=white" />
  <img src="https://img.shields.io/badge/Just-000000?style=for-the-badge&logo=gnu-bash&logoColor=white" />
  <img src="https://img.shields.io/badge/Ruff-FCC21B?style=for-the-badge&logo=python&logoColor=black" />
  <img src="https://img.shields.io/badge/License-BSL_1.1-333333?style=for-the-badge&logo=gnu&logoColor=white" />
</p>

<p align="center">
 <a href="#about-the-project">About the Project</a> •
 <a href="#how-it-works">How It Works</a> •
 <a href="#getting-started">Getting Started</a> •
 <a href="#roadmap">Roadmap</a> •
 <a href="#contributing">Contributing</a> •
 <a href="#releases">Releases</a> •
 <a href="#deployment">Deployment</a>
</p>

<br/>

<h2 id="about-the-project">📖 About the Project</h2>

**CanterlotAPI** is the backend engine for a modern book club management app. Today it covers club creation and administration, member invitations and management with a role hierarchy, a collaborative catalog of book suggestions, and each user's account/profile (password or Google authentication, password changes, and a personal reading history).

Orchestrating reading rounds themselves (ranked voting or random draw) is **planned, but not yet implemented** -- see the [Roadmap](#roadmap) below for what's already designed but not yet built.

The full interactive API reference (Swagger UI) lives at [`/docs`](https://api.canterlot.com.br/docs).

<h2 id="how-it-works">🧠 How It Works</h2>

The system is guided by two already-implemented business-rule pillars that manage how readers coexist within a club:

- **Concurrent, Hierarchical Access Control:** Every club workspace has well-defined roles (`OWNER`, `ADMIN`, `MEMBER`). Administrative actions -- role management, member removal/banning, ownership transfer -- follow a strict chain of command: an `ADMIN` can never act on another `ADMIN` or the `OWNER`, shielding the club from unauthorized actions.
- **Autonomous Admission Management:** New members join through invites issued by the club -- a public link (rotatable at any time) or a direct email invite. Admins retain full control over the flow of new members, including manual approval for restricted clubs and banning.

Orchestrating reading sessions (curation -> deliberation -> progress tracking) is the next planned pillar -- the collaborative catalog already exists today as the curation step; deliberation (voting/draw) and progress tracking haven't been built yet (see [Roadmap](#roadmap)).

---

<h2 id="getting-started">🚀 Getting Started</h2>

Our stack uses the **`uv`** package manager and the **`just`** command runner.

### Prerequisites

1. [uv](https://github.com/astral-sh/uv)
2. [Just](https://github.com/casey/just)
3. [Docker Desktop](https://www.docker.com/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/alexbeldam/canterlot-api.git
cd canterlot-api

# 2. Run the automated setup
# This checks your tooling, brings up the containers (Mongo/Redis),
# creates the .env file, and installs all dependencies in milliseconds.
just setup

# 3. Fill in your credentials
# Open the freshly created `.env` file and fill in your keys (Google Books, JWT_SECRET, etc).
```

### Running and Testing

All project management is centralized through `just`. You don't need to manually activate virtual environments.

| Command       | Description                                                                            |
| ------------- | ---------------------------------------------------------------------------------------- |
| `just dev`    | Starts the Uvicorn server with live-reload (`localhost:8000`)                          |
| `just verify` | Runs the full pipeline (lints, type checking, imports, complexity, and coverage tests) |
| `just test`   | Runs the isolated test suite via Pytest                                                |
| `just format` | Applies automatic formatting fixes (Ruff)                                              |

---

<h2 id="roadmap">🗺️ Roadmap</h2>

Features with business rules already designed, but **not yet implemented**:

- **Reading Sessions & Voting:** the full reading-round cycle -- starting a round (automatic draw or curated pool), member-weighted voting, individual progress tracking, and round completion/cancellation.
- **Email verification and change:** email confirmation on signup, and a flow to change an existing account's email.
- **Browsable reading history:** querying (paginated) and removing entries from the personal reading history -- today you can only add to it.
- **Log out of all devices:** ending every active session at once, as a deliberate action independent of a password change.
- **Automatic reading-deadline reminders:** an email notification a day before and on the day of a round's deadline, triggered by an external cron.

Linking external social bridges (Discord/WhatsApp) was considered, but **rejected**: there's currently no way to verify that a link a club admin sends actually leads to appropriate content, and without a moderation team, the risk of abuse (inappropriate content, malware, spam) was considered unacceptable.

---

<h2 id="contributing">🤝 Contributing</h2>

Pull requests are welcome. Before diving in, take a look at [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the codebase's layering conventions, and test expectations -- the highlights:

- Pull requests are opened against `develop`, not `main`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, ...) -- this isn't just style, releases are generated automatically from commit history (see [Releases](#releases) below).
- Before a pull request can be merged, you'll need to sign the [Contributor License Agreement](CLA.md) -- a bot will walk you through it with a single comment reply on your first PR.

---

<h2 id="releases">🏷️ Releases</h2>

Versioning is automated via [`python-semantic-release`](https://python-semantic-release.readthedocs.io/), computing the next [SemVer](https://semver.org/) version from Conventional Commit history -- but it isn't triggered on every merge to `develop`. A maintainer manually dispatches the "Prepare Release" GitHub Actions workflow (with a `dry_run` mode to preview the next version/changelog first), which:

- Bumps the version and regenerates the `LICENSE` file (version, copyright year, and change date).
- Tags the release (`vX.Y.Z`) and publishes a GitHub Release with an automatically generated changelog.
- Promotes `develop` to `main`, which in turn triggers a production deploy (see [Deployment](#deployment) below).

Release notes for each version are published on the repository's [GitHub Releases](https://github.com/alexbeldam/canterlot-api/releases) page.

---

<h2 id="deployment">☁️ Deployment</h2>

The API runs on [Render](https://render.com/), defined as a Blueprint (`render.yaml`): a `canterlot-api` web service alongside a companion `canterlot-redis` instance. It's live at:

👉 **https://api.canterlot.com.br**

Deploys are triggered by a GitHub Actions hook (`.github/workflows/deploy.yml`) on pushes to `main` that touch source or dependency files -- the hook is skipped when `render.yaml` itself changes, since Render's own Blueprint sync picks that case up instead, avoiding a duplicate deploy. MongoDB is hosted externally (its connection string is a Render secret, not part of the Blueprint).

The frontend that consumes this API lives in a separate repository, [alexbeldam/canterlot](https://github.com/alexbeldam/canterlot), and is served at:

👉 **https://canterlot.com.br**

---

<h2 id="license">📄 License</h2>

This project is licensed under the **Business Source License 1.1 (BSL)**. This means anyone can use, modify, and redistribute this code, including for commercial purposes, **except** to operate a competing hosted service that offers substantially similar book-club functionality to Canterlot's to third parties.

That restriction automatically converts, on the "Change Date" specified in the [LICENSE](LICENSE) file, into the **GNU Affero General Public License v3 (AGPLv3)**: unrestricted and fully open source, including the obligation to keep the source of any network-hosted (SaaS) modification open.

---

<p align="center">Made with ⭐</p>
