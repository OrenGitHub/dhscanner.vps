# ARCHITECTURE

Runtime-side view of the stack: who talks to whom, in what order, and
through which storage layer. Complements [`LAYOUT.md`](LAYOUT.md), which
is the disk-side view (which services live in which compose file).

Every service enumerated below is defined in `compose/*.yaml`; see
`LAYOUT.md` for the disk-side breakdown.

## Overview

A scan is one **job**, identified by a random 16-byte hex `job_id`
allocated by the `app` service. The CLI drives the outside of the loop
(create job → upload files → kick off analysis → poll status → collect
results). Everything inside the compose network is driven by a
**status machine in Redis**: a job is always in exactly one
`WaitingFor…` state, one Python worker owns each state, and progress
happens by workers advancing the state after they successfully call
their downstream analysis service.

There are two exit modes, chosen at `/analyze` time via `agent_mode`:

- **Normal mode** — `queryengine` runs a fixed Prolog query list, and
  a `results_worker` post-processes the answer into SARIF stored under
  the `job_id`.
- **Agent mode** — `queryengine` only assembles + persists the
  knowledge base, then finishes the job and hands back a
  `kb_location`. The LLM-driven query loop lives outside this repo
  (see `dhscanner.kbapi` for the query surface, and `GOAL.md` for the
  bigger picture).

## Topology

```text
                       host
                        │
                        │  8000 (public HTTP)
                        ▼
                 ┌─────────────┐
                 │    app      │  FastAPI: /upload, /analyze, /status,
                 │  (FastAPI)  │           /results, /getjobid,
                 └──┬───────┬──┘           /jobids, /jobs, DELETE /jobs/{id}
                    │       │
                    │       │
     writes ┌───────┘       └───────┐ writes
            ▼                       ▼
   ┌────────────────┐      ┌────────────────────┐
   │   mq (Redis)   │      │  shared volume     │
   │                │      │  transient_storage │
   │  coordinator:  │      │                    │
   │  job status,   │      │  raw files,        │
   │  agent_mode,   │      │  native ASTs,      │
   │  kb_location   │      │  dhscanner ASTs,   │
   │                │      │  callables, facts, │
   │                │      │  sqlite metadata   │
   └────────┬───────┘      └─────────┬──────────┘
            │                        │
            │ poll every 1s          │ shared FS
            │ (get_jobs_waiting_for) │
            ▼                        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                    Python workers (workers/*)                 │
   │                                                               │
   │   native_parser        ──HTTP──▶  frontjs / frontts /         │
   │                                   frontphp / frontpy /        │
   │                                   frontrb / frontcs / frontgo │
   │                                   (yaml/yml handled in-proc)  │
   │                                                               │
   │   dhscanner_parser     ──HTTP──▶  parsers                     │
   │   codegen_worker       ──HTTP──▶  codegen                     │
   │   kbgen_worker         ──HTTP──▶  kbgen                       │
   │   queryengine_worker   ──HTTP──▶  queryengine   ─┐            │
   │   results_worker       (no HTTP; reads storage)  │            │
   │                                                  │            │
   │   every worker + app ──HTTP POST /log──▶  logger_server       │
   │                                                  │            │
   └──────────────────────────────────────────────────┼────────────┘
                                                      │
                              queryengine also        │
                              publishes port 3000     │
                              to the host in agent    │
                              mode (kbapi surface)    │
                                                      ▼
                                              (external agent /
                                               kbapi consumers)

   ┌──────────────────┐          ┌────────────────────┐
   │  logger_server   │──SQL──▶  │  logger (Postgres) │
   │  (FastAPI)       │          │  audit-trail rows  │
   └──────────────────┘          └────────────────────┘
```

Only two ports leave the compose network: `app:8000` (the client-facing
HTTP API the CLI talks to) and `queryengine:3000` (the kbapi surface,
used in agent mode). Everything else is internal to the `dhscanner`
docker network.

## The job status pipeline

Job state is a single string key in Redis: `<job_id>` → JSON
`{"status": "<Status>"}`. Statuses are defined in
`coordinator/interface.py` and advance monotonically forward:

```text
   client (CLI) ──/analyze──▶ WaitingForNativeParsing
                                     │
                    native_parser    │  fronts (per language)
                                     ▼
                              WaitingForDhscannerParsing
                                     │
                    dhscanner_parser │  parsers
                                     ▼
                              WaitingForCodegen
                                     │
                    codegen_worker   │  codegen
                                     ▼
                              WaitingForKbgen
                                     │
                    kbgen_worker     │  kbgen
                                     ▼
                              WaitingForQueryengine
                                     │
                    queryengine_worker  queryengine
                                     │
                    ┌────────────────┴────────────────┐
                    │ agent_mode = true              │ agent_mode = false
                    ▼                                 ▼
              Finished                        WaitingForResultsGeneration
              (kb_location                           │
               sidecar in Redis)                     │  results_worker
                                                     ▼
                                                  Finished
                                                  (SARIF on shared volume)
```

Each worker follows the same loop (see `workers/interface.py`):

1. `get_jobs_waiting_for(self.status)` — ask Redis which jobs are in
   this worker's owned status.
2. `run(job_id)` for each — do the work (typically: load the previous
   stage's artifact from storage, POST it to the analysis service,
   save the response back to storage).
3. `mark_jobs_finished(job_ids)` — advance those jobs to the next
   status.
4. `await asyncio.sleep(1)` — 1-second poll interval.

There is no push queue: Redis is used as a **status board**, and
workers busy-poll it. This keeps the coordinator surface tiny (a few
GET / KEYS / SET / DEL operations) and lets any worker be restarted
without needing to drain or re-play a queue.

## Storage layers

Four distinct stores, each with a specific role. Nothing crosses
between them except via metadata IDs.

| store                                     | backing              | scope                                                                                    |
|-------------------------------------------|----------------------|------------------------------------------------------------------------------------------|
| **Redis** (`mq`)                          | `redis:7`            | Job status + sidecar keys `<job>:agent_mode`, `<job>:kb_location`. Transient; source of truth for "what stage is this job in?". |
| **Shared volume** (`transient_storage`)   | docker named volume  | Raw file bytes uploaded by the client, plus per-stage artifacts (native AST, dhscanner AST, callables, facts JSON, SARIF output). Written by `app` on upload; consumed / rewritten / deleted by each worker as it advances the job. |
| **SQLite** (in the shared volume, `transient_storage/dhscanner.db`) | sqlite | Per-artifact metadata rows (`FileMetadata`, `NativeAstMetadata`, `DhscannerAstMetadata`, `CallablesMetadata`, `FactsMetadata`, `ResultsMetadata`). Lets workers list "all artifacts of stage X for job Y" without walking the filesystem. |
| **Postgres** (`logger`)                   | `postgres:16`        | Audit-trail `LogMessage` rows written via `logger_server`. Independent of the runtime state — a scan can complete with zero log rows if `logger_server` is unhealthy. |

The lifetime of a job spans all four stores; the operator commands
under `manage` (`--clear-job-id`, `--clear-all`) wipe every one of
them in tandem so an operator's "the job is gone" mental model
matches every backing store (see `app/main.py`'s DELETE handlers and
`storage/local.py`'s `clear_job_state`).

## Two modes at the queryengine stage

Every stage before `queryengine` is identical between the two modes;
the split happens inside `workers/queryengine/main.py`:

- **Normal mode** (`agent_mode = false`) — POST all facts to
  `queryengine:/querycheck`. The response is either a Prolog-style
  finding string (`q<id>([...]): yes`) or a `TimeoutExpired` sentinel.
  Either way it's saved as the job's `results`, the job advances to
  `WaitingForResultsGeneration`, and `results_worker` converts it
  into SARIF.
- **Agent mode** (`agent_mode = true`) — POST all facts to
  `queryengine:/uploadkb`. The response contains a `kb_location` path
  (inside the queryengine container / kbapi-addressable), which is
  stored in Redis under `<job>:kb_location`. The job jumps straight
  to `Finished` — no `results_worker` step, no SARIF. The subsequent
  LLM-driven query loop connects to `queryengine:3000` directly and
  uses the `dhscanner.kbapi` query language.

`GET /results` returns whichever of the two shapes the job produced.
