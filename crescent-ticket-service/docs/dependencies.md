# Dependencies

**Policy**: every direct, development and transitive dependency is pinned to an
exact version **published on or before 2026-09-25**. Stable releases were
preferred over the newest ones. Verified on **2026-11-21**.

## How the policy is enforced

| Mechanism | Where |
|---|---|
| Every Python package (including transitive ones) pinned with `==` | `requirements.txt` (runtime), `requirements-dev.txt` (adds test tools) |
| pip refuses files uploaded after the cutoff | `pip install --uploaded-prior-to 2026-09-26T00:00:00Z ...` (pip >= 26.2; pip 26.2.1 is pinned in the instructions) |
| npm resolves only versions published before the cutoff, records exact versions, requires Node 22 | `database/.npmrc` (`before=2026-09-25T23:59:59Z`, `save-exact=true`, `engine-strict=true`) |
| npm installs exactly the locked tree, verified by sha512 integrity | `database/package-lock.json` + `npm ci` |
| Re-verification | `python scripts/check_dependencies.py` - checks pins, that the active environment contains exactly the pinned packages, each version's publication time on PyPI/npm, npm lockfile integrity against the registry, and known vulnerabilities (OSV). `--offline` skips the network checks. The offline checks also run in the test suite (`tests/test_dependencies.py`). |

No Git dependencies, CDN downloads, runtime downloads or custom binary
installers are used. All packages come from the public PyPI and npm registries.

## Where installation was actually tested

| Environment | Python | Node.js / npm | Result |
|---|---|---|---|
| Windows 11 (x64) | 3.13.7 | 22.20.0 / 10.9.3 | install, `pip check`, full test suite, smoke test, online check |
| Ubuntu 24.04.3 LTS on WSL2 (x86_64), clean copy of the project | 3.12.3 | 22.23.3 / 10.9.9 | every README command, full test suite, smoke test, all `api_examples.md` commands, online check |

Both used the public registries (pypi.org, registry.npmjs.org). Installation
from a restricted/internal package mirror was **not** tested.

## Python packages

Publication time = earliest file upload for that version on PyPI.
Source: `https://pypi.org/pypi/<package>/<version>/json`.
Vulnerabilities: OSV (`https://api.osv.dev/v1/querybatch`), queried 2026-11-21.

### Runtime (`requirements.txt`)

| Package | Version | Published (UTC) | Required by | Known vulnerabilities |
|---|---|---|---|---|
| fastapi | 0.141.1 | 2026-07-29 17:18 | direct | none |
| starlette | 1.7.0 | 2026-09-23 07:30 | fastapi | none |
| annotated-doc | 0.0.5 | 2026-07-28 13:50 | fastapi | none |
| anyio | 4.15.1 | 2026-09-05 10:42 | starlette | none |
| idna | 3.20 | 2026-09-17 14:11 | anyio | none |
| uvicorn | 0.53.0 | 2026-09-14 07:44 | direct | none |
| click | 8.5.0 | 2026-08-26 13:33 | uvicorn | none |
| h11 | 0.16.0 | 2025-04-24 03:35 | uvicorn | none |
| pydantic | 2.13.5 | 2026-08-28 14:03 | direct | none |
| pydantic-core | 2.46.5 | 2026-08-28 09:57 | pydantic (exact pin) | none |
| annotated-types | 0.8.0 | 2026-07-23 20:16 | pydantic | none |
| typing-extensions | 4.16.0 | 2026-07-02 08:40 | pydantic, fastapi, sqlalchemy, alembic, anyio | none |
| typing-inspection | 0.4.4 | 2026-08-12 12:37 | pydantic, fastapi, pydantic-settings | none |
| pydantic-settings | 2.15.0 | 2026-08-07 09:24 | direct | none |
| python-dotenv | 1.2.3 | 2026-08-16 16:54 | pydantic-settings | none |
| SQLAlchemy | 2.0.54 | 2026-09-15 21:06 | direct | none |
| greenlet | 3.5.6 | 2026-09-14 14:21 | sqlalchemy (x86_64/amd64/aarch64/ppc64le only) | none |
| alembic | 1.19.2 | 2026-09-04 17:10 | direct | none |
| Mako | 1.4.3 | 2026-09-22 20:54 | alembic | none |
| MarkupSafe | 3.0.3 | 2025-09-27 18:36 | mako | none |
| psycopg2-binary | 2.9.13 | 2026-09-09 23:54 | direct (PostgreSQL driver) | none |

### Development and test (`requirements-dev.txt`)

| Package | Version | Published (UTC) | Required by | Known vulnerabilities |
|---|---|---|---|---|
| pytest | 9.1.1 | 2026-06-19 10:58 | direct | none |
| iniconfig | 2.3.0 | 2025-10-18 21:55 | pytest | none |
| packaging | 26.3 | 2026-08-04 18:15 | pytest | none |
| pluggy | 1.6.0 | 2025-05-15 12:30 | pytest | none |
| Pygments | 2.21.0 | 2026-08-17 08:02 | pytest | none |
| colorama | 0.4.6 | 2022-10-25 02:36 | pytest (Windows only) | none |
| httpx | 0.28.1 | 2024-12-06 15:37 | direct (FastAPI TestClient) | none |
| httpcore | 1.0.9 | 2025-04-24 22:06 | httpx | none |
| certifi | 2026.7.22 | 2026-07-22 03:35 | httpx, httpcore | **GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320** - see below |

### Installer tooling

| Tool | Version | Published | Notes |
|---|---|---|---|
| pip | 26.2.1 | 2026-08-04 | Installed first so `--uploaded-prior-to` is available. OSV: none. Uses the operating-system trust store (truststore) for HTTPS, not certifi. |

## npm packages (`database/package-lock.json`)

Publication time = `time[<version>]` from `https://registry.npmjs.org/<package>`;
the lockfile `integrity` hash was compared with the registry's `dist.integrity`
for every package (all match). `npm audit`: 0 vulnerabilities; OSV: none.

| Package | Version | Published (UTC) | Why it is installed |
|---|---|---|---|
| @electric-sql/pglite | 0.5.8 | 2026-08-26 18:40 | direct: embedded PostgreSQL 18.3 (WebAssembly) |
| @electric-sql/pglite-socket | 0.2.11 | 2026-08-26 18:36 | direct: PostgreSQL wire-protocol socket server |
| @electric-sql/pglite-age | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pg_hashids | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pg_ivm | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pg_textsearch | 0.0.10 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pg_uuidv7 | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pgtap | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |
| @electric-sql/pglite-pgvector | 0.0.9 | 2026-08-26 18:34 | peer dependency of pglite-socket |

pglite-socket 0.2.11 declares seven official PGlite extension packages as
non-optional peer dependencies, which npm installs automatically. They are only
loaded when the CLI is started with `--extensions`, which this project never
does; `start-db.mjs` loads no extensions. Skipping them (`legacy-peer-deps`)
was tried and rejected because `npm ls` then reports the tree as broken.

## Runtimes

| Runtime | Version requirement | Notes |
|---|---|---|
| Python | 3.12 or 3.13 (`.python-version`: 3.13) | Verified: 3.13.7 (released 2025-08-14), 3.12.3 (Ubuntu 24.04 system Python). |
| Node.js | 22.x (`engines`, enforced by `engine-strict`) | **Recommended v22.23.3** (released 2026-09-23, the newest Node 22 release on or before the cutoff; it includes the Node 22 security releases of 2026-01-12, 2026-03-24, 2026-06-17 and 2026-07-28). Node 22.20.0 (2025-09-24) also works but lacks those security fixes. Source: `https://nodejs.org/dist/index.json`. |

Node.js security releases 22.23.4 (2026-10-20) and 22.23.5 (2026-11-11) were
published after the cutoff and are therefore not recommended by this policy.
The database server only listens on localhost, which limits exposure; consider
them when the policy is reviewed.

## Known vulnerability: certifi

| | |
|---|---|
| Package | certifi 2026.7.22 (dev/test only: required by httpx and httpcore) |
| Advisory | GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320, published 2026-10-20 |
| Issue | The bundled CA store includes the `emSign ECC Root CA - G3` root; eight intermediates chaining to it have compromised private keys. An on-path attacker holding one could impersonate TLS servers to clients that trust certifi's bundle. |
| Affected | every certifi release from 2019.03.09 up to 2026.10.18 (fixed); **no fixed version exists before the 2026-09-25 cutoff** |
| Exposure in this project | Low. certifi is not in the runtime requirements. The FastAPI TestClient calls the application in-process and opens no network connections. `scripts/smoke_test.py` uses `urllib` with the system trust store. pip uses the system trust store. |
| Decision | Kept at 2026.7.22 to honour the publication cutoff. The decision is recorded in `scripts/check_dependencies.py` (`ACCEPTED_VULNERABILITIES`), which prints it as a warning on every run and fails on any other vulnerability. |
| Alternative | Change `certifi==2026.7.22` to `certifi==2026.10.19` in `requirements-dev.txt` (and drop `--uploaded-prior-to` for that install) to take the fix at the cost of one post-cutoff dev dependency. |

## Version choices

| Decision | Reason |
|---|---|
| SQLAlchemy **2.0.54**, not 2.1.x | 2.1.0 and 2.1.1 were published 1 day and 0 days before the cutoff and were followed by three bug-fix releases within two weeks; the mature 2.0 line is the stable choice. |
| **psycopg2-binary** 2.9.13, not psycopg 3.3.6 | psycopg 3 failed against the PGlite socket server: after any server error it raised `received 0 results from command 'ROLLBACK'`. psycopg2 passed every probe (SSL negotiation, constraint errors, rollback, row locks, concurrent transactions). For production on Supabase, the psycopg project recommends building `psycopg2` from source rather than using the binary wheel. |
| **httpx** 0.28.1, not httpx2 | The specification names HTTPX, and it is stable. Starlette 1.7 emits a deprecation warning recommending the new `httpx2` package (first releases August 2026, still changing rapidly); the warning is filtered in `pyproject.toml`. Revisit when Starlette drops httpx support. |
| uvicorn without `[standard]` extras | Avoids uvloop, httptools, watchfiles and websockets, which this service does not need. |
| pydantic-settings | Typed configuration from environment and `.env`, with `SecretStr` masking. |
| uvicorn 0.53.0, not 0.54.0 | 0.54.0 was published on the cutoff day itself. |

No email-validator, Redis, Celery, Docker, cloud SDKs or AI model APIs are used.
