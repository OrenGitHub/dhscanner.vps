# LAYOUT

Disk-side view of the repo: what lives where. Complements
[`ARCHITECTURE.md`](ARCHITECTURE.md), which is the runtime-side view
(who talks to whom, and in what order).

## Services

The stack is composed from five compose files under `compose/`. Together
they declare 21 services, grouped below by compose file (which is also
the natural role boundary).

### `compose.base.yaml` — shared infrastructure

| service         | source                | role                                          |
|-----------------|-----------------------|-----------------------------------------------|
| `logger`        | `postgres:16` (image) | Postgres DB storing per-job log rows.         |
| `logger_server` | `dhscanner.infra/logger/Dockerfile` | FastAPI in front of `logger`; workers/app POST log rows here. |
| `mq`            | `redis:7` (image)     | Redis, used by the coordinator as the job-status bus. |

### `compose.app.yaml` — public HTTP surface

| service | source            | role                                                                |
|---------|-------------------|---------------------------------------------------------------------|
| `app`   | `dhscanner.infra/app/Dockerfile`  | FastAPI (`dhscanner.infra/app/main.py`) exposed on `:8000`. Handles upload / analyze / status / results / operator endpoints. |

### `compose.fronts.yaml` — per-language native front-ends

One HTTP service per source language, built from
`dhscanner.core/dhscanner.service.fronts/<lang>`. Each accepts a raw
source file and returns that language's native AST (JSON/text). No
shared image — each front is written in the ecosystem native to its
language.

| service    | source (submodule path)                              | native AST endpoint                             |
|------------|------------------------------------------------------|-------------------------------------------------|
| `frontjs`  | `dhscanner.core/dhscanner.service.fronts/js`         | Esprima JS AST (`/to/esprima/js/ast`)           |
| `frontts`  | `dhscanner.core/dhscanner.service.fronts/ts`         | native TS AST (`/to/native/ts/ast`)             |
| `frontphp` | `dhscanner.core/dhscanner.service.fronts/php`        | PHP AST (`/to/php/ast`)                         |
| `frontpy`  | `dhscanner.core/dhscanner.service.fronts/py`         | native Python AST (`/to/native/py/ast`)         |
| `frontrb`  | `dhscanner.core/dhscanner.service.fronts/rb`         | native CRuby AST (`/to/native/cruby/ast`)       |
| `frontcs`  | `dhscanner.core/dhscanner.service.fronts/cs`         | native C# AST (`/to/native/cs/ast`)             |
| `frontgo`  | `dhscanner.core/dhscanner.service.fronts/go`         | native Go AST (`/to/native/go/ast`)             |

YAML/YML have no separate front — the `parsers` service parses them
directly (`dhscanner.infra/workers/native_parser/main.py` short-circuits
the HTTP round trip for these).

### `compose.prebuilt.yaml` — Haskell / Prolog analysis core

| service        | image (committed default)                          | source (submodule, for reading & optional local build)  |
|----------------|----------------------------------------------------|---------------------------------------------------------|
| `parsers`      | `orenishdocker/dhscanner-parsers:<ver>-x64`        | `dhscanner.core/dhscanner.service.parsers`              |
| `codegen`      | `orenishdocker/dhscanner-codegen:<ver>-x64`        | `dhscanner.core/dhscanner.service.codegen`              |
| `kbgen`        | `orenishdocker/dhscanner-kbgen:<ver>-x64`          | `dhscanner.core/dhscanner.service.kbgen`                |
| `queryengine`  | `orenishdocker/dhscanner-queryengine:<ver>-x64`    | `dhscanner.core/dhscanner.service.queryengine`          |

Roles (short — the runtime story is in [`ARCHITECTURE.md`](ARCHITECTURE.md)):

- `parsers` — native front-end AST → normalized `dhscanner.ast`. The
  currently active grammar-coverage work lives here; see
  [`dhscanner.core/dhscanner.service.parsers/AGENTS.md`](../dhscanner.core/dhscanner.service.parsers/AGENTS.md).
- `codegen` — normalized AST → per-callable IR (`actualCallables`).
- `kbgen` — each callable → knowledge-base facts.
- `queryengine` — hosts the assembled kb and answers Prolog queries
  (fixed list in normal mode; kb exposed for LLM-driven query loops in
  agent mode).

### `compose.workers.yaml` — Python job runners

Six Python workers, all built from the same shared image
(`dhscanner.infra/workers/Dockerfile`, `WORKER=<name>` build arg) but
with different entrypoints. Each worker polls Redis for jobs whose
`Status` matches its stage, calls the corresponding analysis service
over HTTP, and advances the job's status. They are the "orchestration
glue" between `app`, the fronts, and the analysis core.

| service              | source                                          | polls status                  | calls                    |
|----------------------|-------------------------------------------------|-------------------------------|--------------------------|
| `native_parser`      | `dhscanner.infra/workers/native_parser`         | `WaitingForNativeParsing`     | fronts (per language)    |
| `dhscanner_parser`   | `dhscanner.infra/workers/dhscanner_parser`      | `WaitingForDhscannerParsing`  | `parsers`                |
| `codegen_worker`     | `dhscanner.infra/workers/codegen`               | `WaitingForCodegen`           | `codegen`                |
| `kbgen_worker`       | `dhscanner.infra/workers/kbgen`                 | `WaitingForKbgen`             | `kbgen`                  |
| `queryengine_worker` | `dhscanner.infra/workers/queryengine`           | `WaitingForQueryengine`       | `queryengine`            |
| `results_worker`     | `dhscanner.infra/workers/results`               | `WaitingForResultsGeneration` | (no HTTP — post-processes stored results into SARIF) |

## Prebuilt Haskell images (and how to opt out)

The four services in `compose.prebuilt.yaml` ship as prebuilt Docker
images from the public `orenishdocker/*` account. Three of them
(`parsers`, `codegen`, `kbgen`) are Haskell/Yesod HTTP services; the
fourth (`queryengine`) wraps SWI-Prolog. They are shipped prebuilt
because rebuilding the Haskell stack on every `docker compose up`
would add noticeable minutes per bring-up, and because the toolchain
(cabal + Happy + Alex + the pinned resolver) is not something we want
every downstream user to reproduce just to scan a repo.

**If you don't want to run stripped upstream binaries**, this is
entirely optional: each of the four submodules under
`dhscanner.core/dhscanner.service.<name>` is a full source tree with
its own `Dockerfile`, and the compose file is a one-line flip per
service — replace the `image: orenishdocker/...` line with

```yaml
build:
  context: ../dhscanner.core/dhscanner.service.<name>
  dockerfile: Dockerfile
```

and the service builds from that submodule on the next `up`. A cold
full-rebuild of all four is around **6 minutes on a modern laptop**,
which is not bad given what you get: reproducible, source-auditable
images with no third-party binary in the runtime path. See
[`RUN.md`](RUN.md) for the exact bring-up flow in both modes.
