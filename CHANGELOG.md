# CHANGELOG

<!-- version list -->

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
