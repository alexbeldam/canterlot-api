# CHANGELOG

<!-- version list -->

## v0.4.0 (2026-09-04)

### Bug Fixes

- **auth**: Dedicate a rate-limit bucket to password-reset code validation
  ([`10a2dc4`](https://github.com/alexbeldam/canterlot-api/commit/10a2dc48eac11f3792d0135a9b6f3624647c65f6))

- **auth**: Defer cookie-expiry settings lookup out of module scope
  ([`906541c`](https://github.com/alexbeldam/canterlot-api/commit/906541c205fe628513d8b08c5b0faace5aa8d4c0))

- **config**: Reject secret keys that fail base64/hex decoding
  ([`6bf5209`](https://github.com/alexbeldam/canterlot-api/commit/6bf5209bca20d25f811c82d4e1fe2294c3e20c38))

- **tests**: Import Mongo/Redis test containers from testcontainers.community
  ([`aa99e48`](https://github.com/alexbeldam/canterlot-api/commit/aa99e48a922cb39f2864be40efcce4efe01367de))

### Features

- Add email client and optionalize google books provider
  ([`7da8484`](https://github.com/alexbeldam/canterlot-api/commit/7da8484bbb539fff2138a0f07d48805311e2f45b))

- Implement Jinja2-driven multi-brand HTML template email rendering engine
  ([`35ec68e`](https://github.com/alexbeldam/canterlot-api/commit/35ec68ec1d790d51826c9135dc56e33cce6d92ec))

- **auth**: Add verification code models, strict password validation, and error types
  ([`84a8433`](https://github.com/alexbeldam/canterlot-api/commit/84a843337816eb55e581e5bc346d0d59f212b567))

- **core**: Implement centralized rate limiter and cache extensions
  ([`f134826`](https://github.com/alexbeldam/canterlot-api/commit/f13482644096f47380a194926c133cfbdca0a6cb))

- **email**: Add oauth welcome template, update verification contexts, and batching logic
  ([`ebab115`](https://github.com/alexbeldam/canterlot-api/commit/ebab1155d834887afa619c8523e40b44abfa94e6))

- **email-verification**: Shorten verification codes to 6 numeric digits
  ([`52f3fdd`](https://github.com/alexbeldam/canterlot-api/commit/52f3fdd3c5f146f2f9ea49b711a0a26b1dbfbca8))

- **emails**: Integrate SAQ worker, policy engine, and Resend webhooks
  ([`fb8eefa`](https://github.com/alexbeldam/canterlot-api/commit/fb8eefaae3cc3e1e89c7d881dfbeaed0f5134e03))

- **users**: Add email preferences schema and suppression tracking
  ([`d3b83f3`](https://github.com/alexbeldam/canterlot-api/commit/d3b83f3ed6374cae7af76370ce33b80e54c48681))

### Refactoring

- **security**: Add a separate secret for hmac
  ([`a332ec5`](https://github.com/alexbeldam/canterlot-api/commit/a332ec5001f0c3fbb45cb8b7db896bfd5ba195af))


## v0.3.0 (2026-07-18)

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


## v0.1.1 (2026-07-17)

### Bug Fixes

- **ci**: Close three gaps in the deploy/quality/release workflow chain
  ([`9aab114`](https://github.com/alexbeldam/canterlot-api/commit/9aab1143c6d75e4d3203cd03f2898693722f4e23))


## v0.1.0 (2026-07-17)

- Initial Release
