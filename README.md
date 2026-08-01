[![pylint](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml)
[![mypy](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml)
[![tests](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml)

## dhscanner.vps

optimized backend for dhscanner

## install

```bash
$ git clone --recurse-submodules https://github.com/OrenGitHub/dhscanner.vps.git
$ cd dhscanner.vps

# set APPROVED_URL_0 and APPROVED_BEARER_TOKEN_0 in .env at repo root
# (see .env.example). --env-file .env is required because -f compose/...
# makes compose's project directory compose/, so .env at the repo root
# is NOT auto-loaded.
# about 3 min. on a modern laptop
$ docker compose --env-file .env -f ./compose/compose.base.yaml -f ./compose/compose.app.yaml -f ./compose/compose.fronts.yaml -f ./compose/compose.prebuilt.yaml -f ./compose/compose.workers.yaml up -d

# install dependencies
$ pipenv shell
$ pipenv install

# start scanning 🙂
$ python -m cli run --scan_dirname repo/you/want/to/scan --ignore_testing_code true
```

## operator commands

Read-only listing and full wipes for the jobs the server still knows about.
All three operations live under the `manage` subcommand and talk to the same
server you scan against (add `--use_external_vps https://...` for a remote vps).

```bash
# list every job id still tracked by redis (one per line, greppable)
$ python -m cli manage --get-all-job-ids

# wipe one job: redis + sqlite + shared volume + postgres logger rows
$ python -m cli manage --clear-job-id <job_id>

# wipe every job (same scope as above, applied to all jobs)
$ python -m cli manage --clear-all
```

The three are mutually exclusive (exactly one is required under `manage`),
and `manage` doesn't take the scan-mode flags. Third-party trees (`vendor`,
`node_modules`, `site_packages`) are pruned automatically during scan-mode
collection.

## launch-local-app (agent-driven launcher)

`launch-local-app` is step 2 of the top-level "scan + interact + fuzz" loop:
once the kb is built, the next move is to actually run the target application
on localhost so subsequent steps can talk to it. This subcommand asks an
OpenAI model to inspect the target repo (README, manifests, docker compose
files, etc.), produces a structured launch plan, executes it against the
host, and probes a healthcheck URL. On failure it feeds the captured
stdout/stderr/probe-error back to the model for a follow-up plan, up to
`--max-iterations` attempts.

The planning round is a tool-using loop, not a single one-shot prompt. The
model has three sandboxed tools — `read_file(path)`, `list_dir(path)`,
`grep(pattern, glob)` — all rooted at the target dir (no `..`, no absolute
paths), so it can actively explore the repo before drafting each plan
(open the *actual* `apps/web/Dockerfile`, list `docker/`, grep for the
port a Next.js app binds, etc.) instead of guessing from the README. The
sequence of tool calls used during each planning round is saved next to
the plan as `iter-NN/tool_transcript.json` for post-mortem inspection.

```bash
# minimum invocation
$ export OPENAI_API_KEY=sk-...
$ python -m cli launch-local-app ../phpbb

# common knobs
$ python -m cli launch-local-app ../phpbb \
    --model gpt-5 \
    --max-iterations 5 \
    --probe-delay 5

# print the first plan and exit without running anything
$ python -m cli launch-local-app ../phpbb --dry-run

# run the accepted plan's cleanup_commands on exit (default: leave running)
$ python -m cli launch-local-app ../phpbb --teardown-on-exit
```

Per-iteration artefacts (the model's plan, captured logs, the probe result)
land under `agent/.launch_logs/<target-basename>/<timestamp>/iter-NN/` so any
iteration can be inspected post-mortem. The default exits with the launched
app **still running** so the next loop step can interact with it; pass
`--teardown-on-exit` to run the accepted plan's cleanup at the end.

### How failures get reported back to the model

Two probe-side guarantees keep the loop tight, so a single bad plan can't
hold the iteration budget hostage:

* **Bounded probe budget.** The healthcheck schema clamps
  `max_attempts ≤ 30`, `request_timeout_seconds ≤ 30`, and
  `delay_between_attempts_seconds ≤ 15`, so the model cannot pick a
  180-attempt probe that would burn 20 minutes per iteration just
  waiting on a port that will never bind. The runner clamps a second
  time inside `_probe` as defense in depth.
* **Docker-aware fast-fail.** When the probe sees 5 consecutive
  connection-refused errors, it asks Docker whether the launch's
  containers are still up — `docker compose ps -a --format json` for a
  compose launch, `docker inspect` for a `docker run --name <name>`
  launch. If at least one container has *exited*, the probe stops
  immediately and feeds the `docker logs --tail=80` of the exited
  container back to the model as part of the rejection reason — so the
  next plan targets the actual crash cause, not guesses. If all
  containers are still *running*, the connection-refused is treated as
  "app still booting" — the consecutive-refused counter resets and the
  probe keeps trying within the budget. This is the right behavior for
  slow-booting dev servers (Next.js dev + Prisma migrations + workspace
  install can easily take 60-90s before the port binds).

### Docker-only launches, built from source

The launcher enforces two disciplines on every plan:

1. **Docker-only.** Every `launch_command` must invoke `docker` or
   `docker compose`. Direct host commands (`python manage.py runserver`,
   `npm start`, `php -S`, `bundle exec rails s`, ...) are rejected at
   apply time and fed back to the model for a follow-up plan.
2. **Built from source.** The container image for the target app must
   be built from this repo (via the repo's own Dockerfile, a Dockerfile
   the model writes inline, or a compose `build:` stanza). Pre-published
   images of the target itself (`image: ghcr.io/<vendor>/<app>:latest`)
   are forbidden. Sidecar services (Postgres, Redis, MinIO, MailHog,
   ...) are the explicit exception — those use upstream `image:` tags
   because they are not under analysis.

The rationale is the property triangle we actually want for an
appsec-target loop:

* **Reproducibility** — each iteration is captured as a Dockerfile (and
  optionally a compose file) the model writes inline via a prep command,
  not as a sequence of side effects on the host.
* **Revertibility** — between rejected iterations the cleanup commands
  (`docker rm -f <name>`, `docker rmi -f <tag>`, `docker compose down -v
  --rmi local`) restore the host to a clean slate, including dropping
  the locally-built image so the next iteration's Dockerfile changes
  actually take effect.
* **Instrumentability** — if you later want to instrument the target's
  source tree (parser hooks, taint tracing inserts, fuzz harness
  counters), the running container will contain those edits. A pulled
  upstream image would silently mask them.

When a repo ships a compose file that uses a pre-published image for the
target service (formbricks's `docker/docker-compose.yml` is exactly this
shape: `image: ghcr.io/formbricks/formbricks:latest`), the model rewrites
that one service's stanza to use `build:` pointing at the repo's own
Dockerfile. Sidecar stanzas stay as-is.

If a target genuinely cannot be Dockerized from source (proprietary base
image, private infrastructure dependency), the model returns
`give_up=true` instead of falling back to either the host or a pulled
upstream artifact.
