# CHANGELOG

<!-- version list -->

## v0.3.0 (2026-07-18)

### Chores

- **ci**: Bump actions/cache from 4 to 6
  ([`4447ca2`](https://github.com/alexbeldam/canterlot-api/commit/4447ca29a4e2862e5e2c03e73dd5395f6bd28d8f))

- **ci**: Bump actions/create-github-app-token from 1 to 3
  ([`ff5bbf4`](https://github.com/alexbeldam/canterlot-api/commit/ff5bbf4e0cf68734dc2ad0d6196cb58d3a621b0a))

- **ci**: Bump astral-sh/setup-uv from 5 to 7
  ([`126079c`](https://github.com/alexbeldam/canterlot-api/commit/126079ca3714c1ba6313939de049ac5dff8b7dc6))

- **ci**: Bump dependabot/fetch-metadata from 2 to 3
  ([`62f3a66`](https://github.com/alexbeldam/canterlot-api/commit/62f3a66cd77751149b25a9da0eff57a6f286fc61))

- **ci**: Bump extractions/setup-just from 2 to 4
  ([`cd89ea6`](https://github.com/alexbeldam/canterlot-api/commit/cd89ea6da908eca30e7f4a150221be038ae8a739))

- **ci**: Surface workflow outcomes in job summaries, not just logs
  ([`a6ce54f`](https://github.com/alexbeldam/canterlot-api/commit/a6ce54fc3de2d4b3c039f88408c4944b6aab3cee))

- **deps**: Bump the patch-and-minor group across 1 directory with 6 updates
  ([`348c962`](https://github.com/alexbeldam/canterlot-api/commit/348c962551a9c56d5f7c52740fe982200e9cb75e))

- **deps**: Update langcodes[data] requirement from >=3.4.0 to >=3.5.1
  ([`f192b42`](https://github.com/alexbeldam/canterlot-api/commit/f192b42f724f986c78b8fbe04178f4668211ecf9))

- **deps**: Update pydantic[email] requirement from >=2.5.0 to >=2.13.4
  ([`11f659b`](https://github.com/alexbeldam/canterlot-api/commit/11f659b7a607844d752b3b8b5bfa9056622520c3))

- **repo**: Update docs template and workspace defaults
  ([`c5b515e`](https://github.com/alexbeldam/canterlot-api/commit/c5b515ee0125c689fe7160e53644abe537b8657e))

### Features

- **logging**: Filter noisy uvicorn access paths
  ([`d7d6c0d`](https://github.com/alexbeldam/canterlot-api/commit/d7d6c0d1469687ea38ce01f5a056e58d48923471))


## v0.2.3 (2026-07-17)

### Bug Fixes

- **ci**: Drop the approval PAT, use GITHUB_TOKEN for both steps
  ([`38c5cae`](https://github.com/alexbeldam/canterlot-api/commit/38c5cae51aef487579d1d5a95d325ad5d500c0ce))

- **ci**: Grant contents:write for enabling Dependabot auto-merge
  ([`35bbdec`](https://github.com/alexbeldam/canterlot-api/commit/35bbdecf3cf2fd99092a7d05db4ea38cb09586ca))


## v0.2.2 (2026-07-17)

### Bug Fixes

- **ci**: Approve Dependabot PRs with a PAT instead of the release App
  ([`66e18f7`](https://github.com/alexbeldam/canterlot-api/commit/66e18f7c4e6cae98d4b23530b3021aecb80af779))


## v0.2.1 (2026-07-17)

### Bug Fixes

- **ci**: Use release App token to approve Dependabot PRs, group updates
  ([`96253b2`](https://github.com/alexbeldam/canterlot-api/commit/96253b29c5f7bee72aff7f90cb988fc0cd893657))


## v0.2.0 (2026-07-17)

### Bug Fixes

- **release**: Regenerate uv.lock's self-version on every release
  ([`a7b1f57`](https://github.com/alexbeldam/canterlot-api/commit/a7b1f57073875ce4fa885247f10604fd44365df2))

### Features

- **ci**: Add Dependabot and auto-promote its merges to main
  ([`bf6c6a0`](https://github.com/alexbeldam/canterlot-api/commit/bf6c6a09902c4d41e222eade6e2a04015ab73ac1))

### Refactoring

- **ci**: Split release.yml into three focused workflows
  ([`67cec9f`](https://github.com/alexbeldam/canterlot-api/commit/67cec9f5fa27d203a09790c4987ff501b24e6447))


## v0.1.1 (2026-07-17)

### Bug Fixes

- **ci**: Close three gaps in the deploy/quality/release workflow chain
  ([`9aab114`](https://github.com/alexbeldam/canterlot-api/commit/9aab1143c6d75e4d3203cd03f2898693722f4e23))


## v0.1.0 (2026-07-17)

- Initial Release
