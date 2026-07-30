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
| `logger_server` | `logger/Dockerfile`   | FastAPI in front of `logger`; workers/app POST log rows here. |
| `mq`            | `redis:7` (image)     | Redis, used by the coordinator as the job-status bus. |

### `compose.app.yaml` — public HTTP surface

| service | source            | role                                                                |
|---------|-------------------|---------------------------------------------------------------------|
| `app`   | `app/Dockerfile`  | FastAPI (`app/main.py`) exposed on `:8000`. Handles upload / analyze / status / results / operator endpoints. |

### `compose.fronts.yaml` — per-language native front-ends

One HTTP service per source language, built from
`dhscanner/dhscanner.0.fronts/<lang>`. Each accepts a raw source file
and returns that language's native AST (JSON/text). No shared image —
each front is written in the ecosystem native to its language.

| service    | source (submodule path)                     | native AST endpoint                             |
|------------|---------------------------------------------|-------------------------------------------------|
| `frontjs`  | `dhscanner/dhscanner.0.fronts/js`           | Esprima JS AST (`/to/esprima/js/ast`)           |
| `frontts`  | `dhscanner/dhscanner.0.fronts/ts`           | native TS AST (`/to/native/ts/ast`)             |
| `frontphp` | `dhscanner/dhscanner.0.fronts/php`          | PHP AST (`/to/php/ast`)                         |
| `frontpy`  | `dhscanner/dhscanner.0.fronts/py`           | native Python AST (`/to/native/py/ast`)         |
| `frontrb`  | `dhscanner/dhscanner.0.fronts/rb`           | native CRuby AST (`/to/native/cruby/ast`)       |
| `frontcs`  | `dhscanner/dhscanner.0.fronts/cs`           | native C# AST (`/to/native/cs/ast`)             |
| `frontgo`  | `dhscanner/dhscanner.0.fronts/go`           | native Go AST (`/to/native/go/ast`)             |

YAML/YML have no separate front — the `parsers` service parses them
directly (`workers/native_parser/main.py` short-circuits the HTTP round
trip for these).

### `compose.prebuilt.yaml` — Haskell / Prolog analysis core

| service        | image (committed default)                          | source (submodule, for reading & optional local build) |
|----------------|----------------------------------------------------|--------------------------------------------------------|
| `parsers`      | `orenishdocker/dhscanner-parsers:<ver>-x64`        | `dhscanner/dhscanner.1.parsers`                        |
| `codegen`      | `orenishdocker/dhscanner-codegen:<ver>-x64`        | `dhscanner/dhscanner.codegen`                          |
| `kbgen`        | `orenishdocker/dhscanner-kbgen:<ver>-x64`          | `dhscanner/dhscanner.kbgen`                            |
| `queryengine`  | `orenishdocker/dhscanner-queryengine:<ver>-x64`    | `dhscanner/dhscanner.query.engine`                     |

Roles (short — the runtime story is in [`ARCHITECTURE.md`](ARCHITECTURE.md)):

- `parsers` — native front-end AST → normalized `dhscanner.ast`. The
  currently active grammar-coverage work lives here; see
  [`dhscanner/dhscanner.1.parsers/AGENTS.md`](dhscanner/dhscanner.1.parsers/AGENTS.md).
- `codegen` — normalized AST → per-callable IR (`actualCallables`).
- `kbgen` — each callable → knowledge-base facts.
- `queryengine` — hosts the assembled kb and answers Prolog queries
  (fixed list in normal mode; kb exposed for LLM-driven query loops in
  agent mode).

### `compose.workers.yaml` — Python job runners

Six Python workers, all built from the same shared image
(`workers/Dockerfile`, `WORKER=<name>` build arg) but with different
entrypoints. Each worker polls Redis for jobs whose `Status` matches
its stage, calls the corresponding analysis service over HTTP, and
advances the job's status. They are the "orchestration glue" between
`app`, the fronts, and the analysis core.

| service              | source                    | polls status                  | calls                    |
|----------------------|---------------------------|-------------------------------|--------------------------|
| `native_parser`      | `workers/native_parser`   | `WaitingForNativeParsing`     | fronts (per language)    |
| `dhscanner_parser`   | `workers/dhscanner_parser`| `WaitingForDhscannerParsing`  | `parsers`                |
| `codegen_worker`     | `workers/codegen`         | `WaitingForCodegen`           | `codegen`                |
| `kbgen_worker`       | `workers/kbgen`           | `WaitingForKbgen`             | `kbgen`                  |
| `queryengine_worker` | `workers/queryengine`     | `WaitingForQueryengine`       | `queryengine`            |
| `results_worker`     | `workers/results`         | `WaitingForResultsGeneration` | (no HTTP — post-processes stored results into SARIF) |

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
entirely optional: each of the four submodules under `dhscanner/` is a
full source tree with its own `Dockerfile`, and the compose file is a
one-line flip per service — replace the `image: orenishdocker/...`
line with

```yaml
build:
  context: ../dhscanner/<submodule>
  dockerfile: Dockerfile
```

and the service builds from that submodule on the next `up`. A cold
full-rebuild of all four is around **6 minutes on a modern laptop**,
which is not bad given what you get: reproducible, source-auditable
images with no third-party binary in the runtime path. See
[`RUN.md`](RUN.md) for the exact bring-up flow in both modes.
