# pylint: disable=too-many-lines
"""Agent-driven local-app launcher.

Given a path to a third-party application's repository, this module asks
an OpenAI model to draft a launch plan (preparation commands, the main
launch command, an HTTP healthcheck, and optional cleanup commands),
executes that plan against the host, and probes the healthcheck. On
failure the captured stdout/stderr/probe-error is fed back to the model
for a follow-up plan, up to ``max_iterations`` attempts.

This is step 2 of the top-level main loop:

    1. build the kb (already done by `cli.py run --with_agent`)
 -> 2. launch the underlying application on localhost  (THIS MODULE)
    3. let an LLM interact with the kb
    4. fuzz the app with data collected in step 3

The public entry point is ``launch(parsed_args)``, which the CLI
dispatcher in ``cli.py`` calls. It logs through the root logger (so the
existing ``cli_logger.configure()`` palette applies).

Design notes:

* Plans are exchanged as structured JSON (OpenAI ``response_format``
  ``json_schema``). The schema is intentionally narrow -- argv lists,
  not shell strings -- so the planner cannot smuggle shell metacharacters
  past us.
* ``launch_command.keeps_running`` distinguishes
  ``docker compose up -d`` style commands (which return immediately) from
  ``python manage.py runserver`` style commands (which the launcher
  must hold onto via Popen so it can kill them between iterations).
* Per-iteration artefacts (the model's plan, captured stdout/stderr,
  the probe result) are persisted under ``agent/.launch_logs/<basename>/
  <timestamp>/iter-<n>/`` so any iteration can be inspected post-mortem.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import json
import logging
import os
import pathlib
import platform
import re
import subprocess
import sys
import time
import typing

import requests

from argparse_wrapper import CliLaunchLocalAppArgparse


HERE: typing.Final[pathlib.Path] = pathlib.Path(__file__).resolve().parent
LAUNCH_LOGS_ROOT: typing.Final[pathlib.Path] = HERE / '.launch_logs'

DEFAULT_MODEL: typing.Final[str] = 'gpt-5'

# How much of each file we ship to the model. Bounded so that even a
# repo with a 50k-line README doesn't blow the context window.
MAX_README_BYTES: typing.Final[int] = 16_384
MAX_MANIFEST_BYTES: typing.Final[int] = 8_192
MAX_TREE_ENTRIES: typing.Final[int] = 400

# Manifests / build descriptors we surface up-front. Order matters: the
# model sees them in this order, so docker artefacts come first (we
# prefer dockerized launches when both options exist).
KNOWN_MANIFESTS: typing.Final[tuple[str, ...]] = (
    'docker-compose.yml',
    'docker-compose.yaml',
    'compose.yml',
    'compose.yaml',
    'Dockerfile',
    'package.json',
    'pyproject.toml',
    'requirements.txt',
    'Pipfile',
    'Pipfile.lock',
    'setup.py',
    'setup.cfg',
    'Gemfile',
    'composer.json',
    'go.mod',
    'pom.xml',
    'build.gradle',
    'build.gradle.kts',
    'Cargo.toml',
    '.env.example',
    '.env.sample',
    'Makefile',
)

README_NAMES: typing.Final[tuple[str, ...]] = (
    'README.md',
    'README.rst',
    'README.txt',
    'README',
    'readme.md',
)

DIRS_TO_SKIP_IN_TREE: typing.Final[set[str]] = {
    '.git',
    'node_modules',
    'vendor',
    'site-packages',
    'site_packages',
    '__pycache__',
    '.venv',
    'venv',
    'env',
    '.idea',
    '.vscode',
    'dist',
    'build',
    'target',
    '.next',
    '.nuxt',
    '.cache',
}


# --------------------------------------------------------------------------- #
# Plan schema (passed verbatim to OpenAI as response_format json_schema)      #
# --------------------------------------------------------------------------- #

# Notes on the schema:
# - argv lists only: no shell strings, no `&&`, no pipes. If the model
#   needs a shell pipeline it must split it into multiple commands.
# - cwd is interpreted relative to target_dir (or absent for target_dir
#   itself). We refuse absolute paths or `..` traversal at apply time.
# - cleanup_commands run BETWEEN iterations (to undo prep/launch side
#   effects before the next plan tries again) and OPTIONALLY at exit on
#   success via --teardown-on-exit.
LAUNCH_PLAN_SCHEMA: typing.Final[dict[str, typing.Any]] = {
    'name': 'LaunchPlan',
    'strict': True,
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'summary': {'type': 'string'},
            'env': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'name': {'type': 'string'},
                        'value': {'type': 'string'},
                    },
                    'required': ['name', 'value'],
                },
            },
            'prep_commands': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'description': {'type': 'string'},
                        'argv': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'minItems': 1,
                        },
                        'cwd': {'type': ['string', 'null']},
                        'timeout_seconds': {'type': 'integer'},
                    },
                    'required': ['description', 'argv', 'cwd', 'timeout_seconds'],
                },
            },
            'launch_command': {
                'type': ['object', 'null'],
                'additionalProperties': False,
                'properties': {
                    'description': {'type': 'string'},
                    'argv': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'minItems': 1,
                    },
                    'cwd': {'type': ['string', 'null']},
                    'timeout_seconds': {'type': 'integer'},
                    'keeps_running': {'type': 'boolean'},
                },
                'required': [
                    'description', 'argv', 'cwd',
                    'timeout_seconds', 'keeps_running',
                ],
            },
            'healthcheck': {
                'type': ['object', 'null'],
                'additionalProperties': False,
                'properties': {
                    'url': {'type': 'string'},
                    'method': {'type': 'string'},
                    'expected_status_codes': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'minItems': 1,
                    },
                    'request_timeout_seconds': {
                        'type': 'integer', 'minimum': 1, 'maximum': 30,
                    },
                    'max_attempts': {
                        'type': 'integer', 'minimum': 1, 'maximum': 30,
                    },
                    'delay_between_attempts_seconds': {
                        'type': 'integer', 'minimum': 1, 'maximum': 15,
                    },
                },
                'required': [
                    'url', 'method', 'expected_status_codes',
                    'request_timeout_seconds', 'max_attempts',
                    'delay_between_attempts_seconds',
                ],
            },
            'cleanup_commands': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'description': {'type': 'string'},
                        'argv': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'minItems': 1,
                        },
                        'cwd': {'type': ['string', 'null']},
                        'timeout_seconds': {'type': 'integer'},
                    },
                    'required': ['description', 'argv', 'cwd', 'timeout_seconds'],
                },
            },
            'give_up': {'type': 'boolean'},
            'give_up_reason': {'type': 'string'},
        },
        'required': [
            'summary', 'env', 'prep_commands', 'launch_command',
            'healthcheck', 'cleanup_commands', 'give_up', 'give_up_reason',
        ],
    },
}


# --------------------------------------------------------------------------- #
# Plan-time tools (OpenAI function-calling)                                   #
# --------------------------------------------------------------------------- #
#
# The single one-shot prompt was hitting a real architectural ceiling on
# monorepo SPAs: the model could see only what we chose to ship in the
# prompt (root README + root manifests + a depth-limited tree), so when a
# build failed because of e.g. `apps/web/Dockerfile`'s BuildKit-secret
# usage, the model had no way to read the offending file -- it could only
# guess. Giving the model three small tools (read_file / list_dir / grep)
# lets it dive deeper on its own, *before* it commits to a plan, so plans
# can patch existing files instead of rewriting them blind.
#
# All three tools are sandboxed to target_dir via the same path validator
# the launch / prep / cleanup pipeline already uses (`_validate_relative_cwd`),
# so a stray '..' in a tool call can't escape the repo.

MAX_TOOL_CALLS_PER_PLAN: typing.Final[int] = 20

MAX_TOOL_OUTPUT_BYTES: typing.Final[int] = 16_384
MAX_LIST_DIR_ENTRIES: typing.Final[int] = 200
MAX_GREP_HITS: typing.Final[int] = 200
MAX_GREP_FILES: typing.Final[int] = 500
MAX_GREP_LINE_BYTES: typing.Final[int] = 240

LAUNCH_PLAN_TOOLS: typing.Final[list[dict[str, typing.Any]]] = [
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': (
                'Read a UTF-8 text file from the target repo. Returns up to '
                f'{MAX_TOOL_OUTPUT_BYTES} bytes; if the file is larger, only '
                'the tail is returned. Use this on Dockerfiles, compose '
                'files, package.json, .env.example, etc. before drafting '
                'your plan, especially when the file lives in a '
                'subdirectory (e.g. apps/web/Dockerfile).'
            ),
            'parameters': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': (
                            "Path relative to target_dir, posix-style. "
                            "Examples: 'apps/web/Dockerfile', "
                            "'docker/docker-compose.yml'. No absolute "
                            "paths and no '..' traversal."
                        ),
                    },
                },
                'required': ['path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_dir',
            'description': (
                'List the immediate entries of a directory in the target '
                'repo. Use this to discover Dockerfiles / compose files / '
                'env templates that live in monorepo subdirs (apps/*/, '
                'services/*/, docker/, deploy/, infra/, ...). Returns up '
                f'to {MAX_LIST_DIR_ENTRIES} entries.'
            ),
            'parameters': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': (
                            "Directory path relative to target_dir. Use "
                            "'' or '.' for the repo root."
                        ),
                    },
                },
                'required': ['path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'grep',
            'description': (
                'Search for a Python regex across files matching a glob. '
                'Returns matching `path:line:text` triples, capped at '
                f'{MAX_GREP_HITS} hits. Useful for finding e.g. the actual '
                'port the app binds, env-var names the code reads, the '
                'definition of a build script, etc. Skips node_modules, '
                '.git, .next, dist, build, .venv, vendor, and other '
                'known-noisy trees.'
            ),
            'parameters': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'pattern': {
                        'type': 'string',
                        'description': (
                            'Python `re`-compatible regex. Case-sensitive '
                            'by default; embed `(?i)` to make it '
                            'case-insensitive.'
                        ),
                    },
                    'glob': {
                        'type': 'string',
                        'description': (
                            "Posix-style glob (matches against repo-rooted "
                            "paths). Examples: '**/Dockerfile*', "
                            "'apps/**/*.ts', 'docker/*.yml'. Use '**/*' "
                            "to search everywhere (slower)."
                        ),
                    },
                },
                'required': ['pattern', 'glob'],
            },
        },
    },
]


# Trees pruned during list_dir / grep traversal. Mirrors the visual-tree
# DIRS_TO_SKIP_IN_TREE but is intentionally a separate constant so the
# two can drift apart (e.g. we may want grep to look inside .git history
# someday; we never want the visual tree to).
_DIRS_PRUNED_FROM_TOOLS: typing.Final[frozenset[str]] = frozenset({
    '.git',
    'node_modules',
    'vendor',
    'site-packages',
    'site_packages',
    '__pycache__',
    '.venv',
    'venv',
    'env',
    '.next',
    '.nuxt',
    '.cache',
    'dist',
    'build',
    'target',
    '.turbo',
    '.pnpm-store',
})


# pylint: disable=too-many-return-statements
def _resolve_tool_path(
    target_dir: pathlib.Path,
    raw: str,
    must_be_dir: bool,
) -> pathlib.Path | str:
    """Validate a tool-supplied path and return the absolute path under
    target_dir, or an error string for the model.

    Same shape as `_validate_relative_cwd` (return-on-error rather than
    raise) so the tool-dispatch layer can turn errors into tool results
    the model sees, instead of crashing the iteration loop.
    """
    if raw is None:
        return 'path argument is required'
    cleaned = raw.strip()
    if cleaned in ('', '.'):
        resolved = target_dir
    else:
        candidate = pathlib.Path(cleaned)
        if candidate.is_absolute():
            return f"path must be relative, got absolute: {raw!r}"
        if any(p == '..' for p in candidate.parts):
            return f"path must not contain '..' traversal, got: {raw!r}"
        resolved = (target_dir / candidate).resolve()
    try:
        resolved.relative_to(target_dir.resolve())
    except ValueError:
        return f"path escapes target_dir: {raw!r}"
    if must_be_dir:
        if not resolved.is_dir():
            return f"not a directory (or does not exist): {raw!r}"
    elif not resolved.is_file():
        return f"not a file (or does not exist): {raw!r}"
    return resolved


def _tool_read_file(target_dir: pathlib.Path, args: dict[str, typing.Any]) -> str:
    resolved = _resolve_tool_path(target_dir, args.get('path', ''), must_be_dir=False)
    if isinstance(resolved, str):
        return f'ERROR: {resolved}'
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        return f'ERROR: could not read file: {exc}'
    truncated = len(data) > MAX_TOOL_OUTPUT_BYTES
    body = data[-MAX_TOOL_OUTPUT_BYTES:] if truncated else data
    text = body.decode('utf-8', errors='replace')
    prefix = (
        f'... <truncated head; {len(data) - MAX_TOOL_OUTPUT_BYTES} earlier '
        f'bytes omitted>\n'
        if truncated else ''
    )
    return prefix + text


def _tool_list_dir(target_dir: pathlib.Path, args: dict[str, typing.Any]) -> str:
    resolved = _resolve_tool_path(target_dir, args.get('path', ''), must_be_dir=True)
    if isinstance(resolved, str):
        return f'ERROR: {resolved}'
    try:
        entries = sorted(
            resolved.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except OSError as exc:
        return f'ERROR: could not list directory: {exc}'
    out_lines: list[str] = []
    truncated = False
    for entry in entries:
        if len(out_lines) >= MAX_LIST_DIR_ENTRIES:
            truncated = True
            break
        if entry.is_dir() and entry.name in _DIRS_PRUNED_FROM_TOOLS:
            continue
        suffix = '/' if entry.is_dir() else ''
        try:
            size = entry.stat().st_size if not entry.is_dir() else None
        except OSError:
            size = None
        size_part = f'  ({size} bytes)' if size is not None else ''
        out_lines.append(f'{entry.name}{suffix}{size_part}')
    if truncated:
        out_lines.append(f'... <truncated; only first {MAX_LIST_DIR_ENTRIES} shown>')
    if not out_lines:
        return '(empty directory or all entries pruned)'
    return '\n'.join(out_lines)


# pylint: disable=too-many-locals,too-many-branches,too-many-return-statements,too-many-statements
def _tool_grep(target_dir: pathlib.Path, args: dict[str, typing.Any]) -> str:
    pattern = args.get('pattern')
    glob_pat = args.get('glob')
    if not isinstance(pattern, str):
        return 'ERROR: pattern is required and must be a string'
    if not isinstance(glob_pat, str) or not glob_pat:
        return 'ERROR: glob is required and must be a non-empty string'
    # An empty pattern degrades to "list files matching the glob"
    # (i.e. `find -name`). The first iteration showed the model
    # naturally used this shape -- it ran
    # grep(pattern='', glob='**/Dockerfile*') exactly as the prompt
    # suggested, and the tool slapped it down. List-mode is what was
    # actually wanted: a fast "do any files match this glob?" probe
    # before paying the cost of reading them.
    list_mode = pattern == ''
    regex: re.Pattern[str] | None = None
    if not list_mode:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f'ERROR: invalid regex {pattern!r}: {exc}'

    # Walk target_dir once; for each file path posix-relative to
    # target_dir, check both fnmatch (cheap glob shape) AND ensure we
    # haven't hit any of our pruned dirs. Two-pass walks would risk
    # missing files inside reasonable subdirs of pruned-named parents
    # (e.g. a `vendor` repo of yours, not a node-modules `vendor`); we
    # prefer the simpler "skip pruned dirs at walk time".
    root = target_dir.resolve()
    matched_paths: list[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _DIRS_PRUNED_FROM_TOOLS]
        for name in filenames:
            abs_path = pathlib.Path(dirpath) / name
            try:
                rel = abs_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if fnmatch.fnmatch(rel, glob_pat) or fnmatch.fnmatch(name, glob_pat):
                matched_paths.append(abs_path)
                if len(matched_paths) >= MAX_GREP_FILES:
                    break
        if len(matched_paths) >= MAX_GREP_FILES:
            break

    if not matched_paths:
        return f'(no files matched glob {glob_pat!r})'

    if list_mode:
        rels = [p.relative_to(root).as_posix() for p in matched_paths]
        truncated = len(rels) >= MAX_GREP_FILES
        body = '\n'.join(rels)
        if truncated:
            body += (
                f'\n... <truncated; only first {MAX_GREP_FILES} matching '
                'paths shown>'
            )
        return body

    assert regex is not None
    hits: list[str] = []
    files_scanned = 0
    for abs_path in matched_paths:
        if len(hits) >= MAX_GREP_HITS:
            break
        try:
            text = abs_path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        rel = abs_path.relative_to(root).as_posix()
        files_scanned += 1
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                stripped = line.rstrip('\r\n')
                if len(stripped) > MAX_GREP_LINE_BYTES:
                    stripped = stripped[:MAX_GREP_LINE_BYTES] + '...'
                hits.append(f'{rel}:{lineno}:{stripped}')
                if len(hits) >= MAX_GREP_HITS:
                    break

    if not hits:
        return (
            f'(0 hits across {files_scanned} files matching {glob_pat!r})'
        )
    suffix = ''
    if len(hits) >= MAX_GREP_HITS:
        suffix = f'\n... <truncated; only first {MAX_GREP_HITS} hits shown>'
    return '\n'.join(hits) + suffix


_TOOL_DISPATCH: typing.Final[dict[str, typing.Callable[[pathlib.Path, dict[str, typing.Any]], str]]] = {
    'read_file': _tool_read_file,
    'list_dir':  _tool_list_dir,
    'grep':      _tool_grep,
}


def _dispatch_tool_call(
    name: str,
    raw_args: str,
    target_dir: pathlib.Path,
) -> str:
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return f'ERROR: unknown tool {name!r}'
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return f'ERROR: tool arguments were not valid JSON: {exc}'
    if not isinstance(args, dict):
        return 'ERROR: tool arguments must be a JSON object'
    return handler(target_dir, args)


SYSTEM_PROMPT: typing.Final[str] = """\
You are an expert release engineer driving a one-shot "launch this repo on \
localhost" task. Each turn you produce a structured launch plan in JSON \
matching the LaunchPlan schema; an automated runner applies it and either \
reports success or feeds you back the captured stdout/stderr/healthcheck \
error so you can correct the plan on the next turn.

Hard rules (the runner enforces them):

1. argv lists only. No shell pipelines, no `&&`, no `;`, no globbing. \
   If you need a shell pipeline, decompose it into multiple prep_commands.
2. cwd is interpreted relative to the target_dir, or use null to mean \
   target_dir itself. Absolute paths and `..` traversal are rejected.
3. **Docker-only execution.** Every launch MUST run the target app inside \
   a container, never directly on the host. The launch_command MUST be \
   one of:
     - `docker run ... <image>` (after a `docker build` prep step), or
     - `docker compose up -d` (after writing a compose file in a prep \
       step if none exists), or
     - `docker compose run --rm <service>` for one-shots that exit.
   Direct host commands (`python manage.py runserver`, `npm start`, \
   `php -S`, `bundle exec rails s`, ...) are forbidden as launch \
   commands -- they pollute the host, are non-revertible between \
   iterations, and break the demo-reproducibility guarantee that the \
   whole loop is built around. If the repo has no Dockerfile / compose \
   file, write one yourself as a prep_command (heredoc-style) before \
   the `docker build` / `docker compose up` step. Pin a specific base \
   image tag (e.g. `php:8.2-apache`, not `php:latest`) so re-runs are \
   reproducible.
4. **Build the target app from this repo's source.** The container \
   image for the target app MUST be built from THIS repo, never \
   `docker pull`'d as a finished artifact from a registry. Acceptable \
   forms:
     - the repo's own Dockerfile (`docker build -f apps/web/Dockerfile \
       -t <target>-local .` or similar), or
     - a Dockerfile you write inline in a prep step (heredoc), or
     - a compose file with a `build:` stanza pointing at this repo \
       (`build: { context: ., dockerfile: apps/web/Dockerfile }`).
   FORBIDDEN for the target app: `image: ghcr.io/<vendor>/<app>:...`, \
   `image: docker.io/<vendor>/<app>:...`, or any `image:` reference \
   that names the project itself as a pre-published artifact. This is \
   a hard rule, not a preference -- downstream loop steps may \
   instrument the source tree (parser hooks, taint tracing, fuzz \
   harness counters), and a pulled image would silently mask those \
   edits. Even if the upstream publishes a "latest" image of exactly \
   this commit, build it yourself.
   Sidecar services are the exception: Postgres, Redis / Valkey, \
   MailHog, MinIO, RabbitMQ, etc. SHOULD use upstream `image:` tags \
   (`image: postgres:17`, `image: redis:7-alpine`, ...) because they \
   are not under analysis. The rule applies only to the app whose \
   source lives in this repo.
   If the repo ships a compose file that uses `image:` for the target \
   service (formbricks's `docker/docker-compose.yml` is exactly this \
   shape -- `image: ghcr.io/formbricks/formbricks:latest`), rewrite \
   that one service's stanza in a prep step to use `build:` pointing \
   at the repo's own Dockerfile. Keep the sidecar stanzas as-is.
5. **Container/image naming is deterministic.** Pick a stable name \
   derived from the target (e.g. `--name <target>-local`, image tag \
   `<target>-local`) and reuse the same name across iterations. This \
   lets cleanup_commands target it precisely with `docker rm -f \
   <name>` / `docker rmi -f <tag>`. Never pass `--rm` to `docker run` \
   for the launch_command -- the runner wants the container to survive \
   for post-mortem inspection and for the next loop step (kb query / \
   fuzz) to attach to it.
6. **Host port binding is explicit.** When you publish ports, bind to \
   loopback only: `-p 127.0.0.1:<host>:<container>`. The healthcheck \
   probe runs on the host, not inside the container, so the port must \
   be reachable from the host. Pick a host port unlikely to clash \
   (8000-9999 range; avoid 80/443/3306/5432/6379). Use the same host \
   port across iterations so the healthcheck URL stays stable.
7. launch_command.keeps_running:
   - false: the command exits on its own quickly (e.g. `docker compose \
     up -d`, `docker run -d ...`). The runner waits for it to exit, \
     then probes the healthcheck. Use this for every Docker launch \
     that goes detached; it is the default and the right answer almost \
     always.
   - true: the command stays in the foreground (e.g. `docker compose \
     up` without -d). The runner spawns it, redirects output to a log \
     file, and probes the healthcheck while it stays alive. Rarely \
     needed -- prefer detached + `docker logs` in cleanup.
8. healthcheck.url MUST point at localhost / 127.0.0.1 / a local docker \
   bridge IP. The runner refuses non-local hosts. Pick the *narrowest* \
   path you know returns a non-error HTTP status in the app's bootable \
   state (e.g. a pre-install wizard, a static asset, a public landing \
   page) -- not a path that requires a configured DB / authenticated \
   session unless the plan actually provisions those. \
   **Probe budget is bounded and small on purpose.** \
   `max_attempts` MUST be in [1, 30], `request_timeout_seconds` in \
   [1, 30], `delay_between_attempts_seconds` in [1, 15] -- the schema \
   rejects anything else. Sensible defaults: \
   `max_attempts=20, request_timeout_seconds=5, \
   delay_between_attempts_seconds=3` (worst case ~2 minutes). Do NOT \
   set `max_attempts` to large values like 60/120/180 to "be safe" -- \
   the iteration loop has its own retry budget (`--max-iterations`), \
   so burning 20 minutes on a single failing probe just starves the \
   next iteration's attempt to fix the actual bug. \
   Also: the runner will FAST-FAIL the probe after 5 consecutive \
   "connection refused" errors (TCP RST -- nothing listening on the \
   port). When you see that in the feedback, it does NOT mean "wait \
   longer"; it means the launch_command itself silently failed (the \
   container exited, crash-looped, or you published the wrong host \
   port). Your next plan must investigate (`docker logs <name>` in a \
   prep step, re-read the Dockerfile's EXPOSE, check `-p` mapping), \
   not increase the probe budget.
9. cleanup_commands are run between iterations (to undo what prep / \
   launch did before your next plan retries) and may be run at exit. \
   They MUST be Docker-targeted and idempotent: `docker rm -f \
   <container-name>` and `docker rmi -f <image-tag>` at minimum; \
   `docker compose down -v --rmi local` if you used compose (the \
   `--rmi local` is important when you built from source -- it drops \
   the locally-built image so the next iteration's Dockerfile changes \
   actually take effect). Do NOT include `pkill` / `taskkill` / direct \
   process-level cleanup -- if you followed rule 3 there is no host \
   process to kill.
10. If you cannot see a safe path to a working Docker launch built \
    from this repo's source (e.g. the repo needs a non-public base \
    image, or credentials the runner won't have), set give_up=true \
    with a short give_up_reason and an empty plan. Do NOT fall back \
    to running on the host, and do NOT fall back to pulling a \
    pre-published image of the target.

Exploration tools (use them before you commit to a plan):

You have three tools: `read_file(path)`, `list_dir(path)`, and \
`grep(pattern, glob)`. They are sandboxed to target_dir; '..' and \
absolute paths are rejected. The fixed context shipped at the start \
of this turn (directory tree + root README + root manifests) is a \
*starting point*, not the whole story -- many real repos hide the \
file that actually matters in a subdirectory.

Before drafting the first plan for an unfamiliar repo, do at least \
one exploration round. In particular:

* Dockerfiles live anywhere. The root Dockerfile is the easy case; \
  monorepos very often keep the *real* one at \
  `apps/web/Dockerfile`, `services/<name>/Dockerfile`, \
  `docker/Dockerfile.web`, `deploy/Dockerfile.prod`, etc. ALWAYS \
  `grep(pattern='', glob='**/Dockerfile*')` first, then \
  `read_file(...)` each match you intend to use. \
  (`grep` with an empty pattern lists every file matching the glob \
  -- it acts like `find -name`, no regex compile, much cheaper. \
  This is the canonical way to discover Dockerfiles / composes / \
  any other "where does this file live" question.) \
  Patching an existing Dockerfile (e.g. dropping a \
  `--mount=type=secret` line the runner can't satisfy, swapping a \
  `RUN pnpm build` for a variant that doesn't need a network \
  secret) is almost always cheaper and more reliable than writing \
  a fresh one from scratch.
* Compose files likewise: `grep(pattern='', \
  glob='**/docker-compose*.y*ml')` and \
  `grep(pattern='', glob='**/compose*.y*ml')`. If the project \
  already ships a working compose graph, your plan should reuse it \
  (rewriting only the one stanza that violates rule 4) rather than \
  redefining services from scratch.
* The actual port the app binds is often discoverable: \
  `grep(pattern='EXPOSE ', glob='**/Dockerfile*')`, or \
  `grep(pattern='listen|PORT', glob='**/*.{js,ts,py,php,rb,go}')`. \
  Don't guess the port if you can grep it.
* Env-var contracts: `read_file('.env.example')` or \
  `grep(pattern='process.env.|os.environ', glob='**/*.ts')` -- many \
  apps refuse to start without specific env vars (`NEXTAUTH_URL`, \
  `DATABASE_URL`, `ENCRYPTION_KEY`, ...). Discover them and set \
  them in the plan's `env` field, don't wait for the app to crash.
* For monorepos with multiple deployable surfaces (apps/web, \
  apps/admin, ...), `list_dir('apps')` + `read_file` the README of \
  each to figure out which one is the user-facing target.

The tools cost real budget (each round = an OpenAI call), so don't \
spelunk indefinitely. A reasonable round is: one or two `grep`s for \
Dockerfiles/composes, two or three `read_file`s on the matches, \
then plan. The hard cap is """ + str(MAX_TOOL_CALLS_PER_PLAN) + """ \
tool calls per planning round; after that the runner forces you to \
emit a plan with whatever you've already seen.

Style:

* Keep the plan minimal. The fewer commands, the easier to debug.
* If a previous iteration already passed several prep_commands, you may \
  re-include them (they should be cheap/idempotent) or assume the \
  caller will run only what's missing. The runner reruns the whole plan \
  each iteration; design accordingly.
* The runner reports back: which command failed, captured stdout/stderr \
  tails, and the healthcheck error. Read the feedback carefully before \
  changing the plan -- the most common failure is the wrong healthcheck \
  URL or port, not a fundamentally wrong launch command.
* When you write a Dockerfile inline (via a prep_command), keep it \
  small: one FROM, one COPY, one RUN per concern, EXPOSE the container \
  port. The point is reviewability across iterations, not a production \
  image.
"""


# --------------------------------------------------------------------------- #
# Data classes                                                                #
# --------------------------------------------------------------------------- #


# pylint: disable=too-many-instance-attributes
@dataclasses.dataclass
class CommandResult:
    # All eight fields are part of the feedback we ship back to the
    # model on rejection; trimming any of them would either hide a
    # failure mode or force the model to guess (e.g. "did this time
    # out, or did it just exit non-zero?"). The pylint
    # too-many-instance-attributes nudge doesn't fit a pure data
    # carrier whose shape is dictated by the feedback contract.
    description: str
    argv: list[str]
    cwd: str
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    timed_out: bool
    error: str | None  # set on apply-time validation failure


@dataclasses.dataclass
class ProbeResult:
    url: str
    last_status: int | None
    expected_status_codes: list[int]
    attempts: int
    error: str | None
    response_body_preview: str | None

    @property
    def ok(self) -> bool:
        return (
            self.last_status is not None
            and self.last_status in self.expected_status_codes
        )


@dataclasses.dataclass
class IterationOutcome:
    iteration: int
    plan: dict[str, typing.Any]
    prep_results: list[CommandResult]
    launch_result: CommandResult | None
    probe_result: ProbeResult | None
    accepted: bool
    rejection_reason: str | None


# --------------------------------------------------------------------------- #
# Repo-context collection                                                     #
# --------------------------------------------------------------------------- #


def _read_text_truncated(path: pathlib.Path, max_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f'<unreadable: {exc}>'
    truncated = data[:max_bytes]
    text = truncated.decode('utf-8', errors='replace')
    if len(data) > max_bytes:
        text += f'\n... <truncated; {len(data) - max_bytes} bytes omitted>'
    return text


def _collect_tree(target_dir: pathlib.Path, max_entries: int) -> list[str]:
    """Return a depth-limited, breadth-first listing of the repo."""
    out: list[str] = []
    queue: list[tuple[pathlib.Path, int]] = [(target_dir, 0)]
    while queue and len(out) < max_entries:
        cur, depth = queue.pop(0)
        if depth > 3:
            continue
        try:
            entries = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            continue
        for entry in entries:
            # Hide dotfiles / dotdirs by default to keep the tree
            # signal-to-noise high. Keep two specific opt-ins that the
            # model often needs in order to draft a working plan
            # (`.env.example` / `.env.sample` enumerate required env
            # vars without leaking real secrets).
            if entry.name.startswith('.') and entry.name not in {'.env.example', '.env.sample'}:
                continue
            if entry.is_dir() and entry.name in DIRS_TO_SKIP_IN_TREE:
                continue
            try:
                rel = entry.relative_to(target_dir).as_posix()
            except ValueError:
                continue
            suffix = '/' if entry.is_dir() else ''
            out.append(f'{rel}{suffix}')
            if len(out) >= max_entries:
                break
            if entry.is_dir():
                queue.append((entry, depth + 1))
    return out


def _collect_manifests(target_dir: pathlib.Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in KNOWN_MANIFESTS:
        candidate = target_dir / name
        if candidate.is_file():
            found[name] = _read_text_truncated(candidate, MAX_MANIFEST_BYTES)
    return found


def _collect_readme(target_dir: pathlib.Path) -> tuple[str, str] | None:
    for name in README_NAMES:
        candidate = target_dir / name
        if candidate.is_file():
            return name, _read_text_truncated(candidate, MAX_README_BYTES)
    return None


# --------------------------------------------------------------------------- #
# Plan validation                                                             #
# --------------------------------------------------------------------------- #


_BANNED_TOKENS: typing.Final[tuple[str, ...]] = ('sudo', 'doas')
_HEALTHCHECK_OK_HOSTS: typing.Final[tuple[str, ...]] = (
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    'host.docker.internal',
)


def _validate_relative_cwd(target_dir: pathlib.Path, raw: str | None) -> pathlib.Path | str:
    """Resolve a plan-provided cwd against target_dir or return an error string.

    The return-on-error pattern keeps the call sites linear (vs. raising)
    because we want to surface the validation message back to the LLM
    rather than crash the loop.
    """
    if raw is None or raw == '':
        return target_dir
    candidate = pathlib.Path(raw)
    if candidate.is_absolute():
        return f'cwd must be relative, got absolute: {raw}'
    parts = candidate.parts
    if any(p == '..' for p in parts):
        return f'cwd must not contain `..` traversal, got: {raw}'
    resolved = (target_dir / candidate).resolve()
    try:
        resolved.relative_to(target_dir.resolve())
    except ValueError:
        return f'cwd escapes target_dir: {raw}'
    if not resolved.is_dir():
        return f'cwd does not exist (or is not a directory): {raw}'
    return resolved


def _validate_argv(argv: list[str]) -> str | None:
    if not argv:
        return 'argv must be non-empty'
    head = argv[0]
    if head in _BANNED_TOKENS:
        return f'banned program: {head}'
    return None


# System prompt rule 3: launch_command MUST be a Docker invocation. We
# only constrain the LAUNCH step (not prep / cleanup); prep legitimately
# uses shells, git, file-writing tooling, etc. to set up the build
# context. Keeping this list small + case-insensitive matches the way
# the model and the runner agree on Docker entry points on
# Linux/macOS/Windows.
_ALLOWED_LAUNCH_HEADS: typing.Final[frozenset[str]] = frozenset({
    'docker',
    'docker.exe',
    'docker-compose',
    'docker-compose.exe',
})


def _validate_launch_argv(argv: list[str]) -> str | None:
    """Enforce the Docker-only launch rule.

    Returns an error message suitable for feeding back to the model when
    a future iteration violates rule 3. The check is intentionally lax
    on the *form* of the docker invocation (`docker run`, `docker
    compose up`, `docker compose run`, ...) so the model retains the
    flexibility to choose the right subcommand for the target; the only
    invariant is that the first program is `docker` (or the legacy
    `docker-compose` v1 binary).
    """
    if not argv:
        return 'launch_command.argv must be non-empty'
    head = pathlib.Path(argv[0]).name.lower()
    if head not in _ALLOWED_LAUNCH_HEADS:
        return (
            f'launch_command must invoke docker (got argv[0]={argv[0]!r}); '
            'system prompt rule 3 forbids host-process launches -- '
            'wrap the target in a Dockerfile / compose file instead.'
        )
    return None


def _validate_healthcheck_url(url: str) -> str | None:
    # Cheap textual check first; we don't want to send any traffic at
    # all if the URL points off-host.
    if '://' not in url:
        return f'healthcheck.url must include a scheme, got: {url}'
    scheme, rest = url.split('://', 1)
    if scheme not in ('http', 'https'):
        return f'healthcheck.url scheme must be http(s), got: {scheme}'
    host_port = rest.split('/', 1)[0]
    host = host_port.split(':', 1)[0] if ':' in host_port else host_port
    host = host.lower()
    if host in _HEALTHCHECK_OK_HOSTS:
        return None
    # Allow any IP in the loopback range. resolve via getaddrinfo so
    # `myapp.local` style mDNS hostnames aren't silently accepted.
    if host.startswith('127.'):
        return None
    return f'healthcheck.url must be localhost / 127.x / a docker bridge host, got: {host}'


# --------------------------------------------------------------------------- #
# Subprocess execution                                                        #
# --------------------------------------------------------------------------- #


_TAIL_BYTES: typing.Final[int] = 4_096


def _tail(text: str | None, max_bytes: int = _TAIL_BYTES) -> str:
    # Accept None defensively: TimeoutExpired / decode-error code paths
    # in subprocess can leave stdout/stderr as None, and callers feed
    # whatever the subprocess returned. A blanket coercion here keeps
    # every call site one-liner-shaped without scattered `or ''` noise.
    if not text:
        return ''
    if len(text) <= max_bytes:
        return text
    return '... <truncated head>\n' + text[-max_bytes:]


def _coerce_to_text(raw: str | bytes | None) -> str:
    """Best-effort 'whatever subprocess gave us' -> str.

    Used by the TimeoutExpired branch where `exc.stdout` / `exc.stderr`
    can be any of the three. We don't want a single byte that isn't
    valid UTF-8 (or a None from "child died before producing output")
    to crash the iteration loop, so we lossy-decode + None-coerce.
    """
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    return raw.decode('utf-8', errors='replace')


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _run_synchronous(
    description: str,
    argv: list[str],
    cwd: pathlib.Path,
    env: dict[str, str],
    timeout_seconds: int,
    log_path: pathlib.Path,
) -> CommandResult:
    """Run `argv` in `cwd`, blocking until it exits or times out.

    Used for prep_commands, cleanup_commands, and for launch_command
    when keeps_running=false. Stdout / stderr are captured AND mirrored
    to `log_path` so a post-mortem can read the full output even after
    we shipped only a tail to the model.
    """
    logging.info('[ launch ] $ %s', ' '.join(argv))
    try:
        # Force UTF-8 decoding instead of relying on
        # locale.getpreferredencoding(). On Windows that defaults to
        # cp1252, which silently chokes on the box-drawing chars and
        # ANSI progress UI that `docker compose build`, pnpm, and
        # most modern toolchains emit -- producing
        # UnicodeDecodeError mid-build and aborting the loop. UTF-8
        # + errors='replace' makes the launcher robust to any byte
        # sequence the child wants to write, at the cost of an
        # occasional U+FFFD in the captured log (acceptable: we're
        # using these tails for model feedback, not for forensics).
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # exc.stdout / exc.stderr can be str (when we pass text=True
        # + encoding) OR bytes (when the child died before any
        # decoding happened) OR None. Cover all three so a docker
        # build timeout doesn't crash the iteration loop the way the
        # first formbricks attempt did.
        out = _coerce_to_text(exc.stdout)
        err = _coerce_to_text(exc.stderr)
        _persist_run_log(log_path, argv, cwd, out, err, exit_code=None, timed_out=True)
        return CommandResult(
            description=description,
            argv=argv,
            cwd=str(cwd),
            exit_code=None,
            stdout_tail=_tail(out),
            stderr_tail=_tail(err),
            timed_out=True,
            error=None,
        )
    except (OSError, ValueError) as exc:
        return CommandResult(
            description=description,
            argv=argv,
            cwd=str(cwd),
            exit_code=None,
            stdout_tail='',
            stderr_tail='',
            timed_out=False,
            error=f'failed to spawn: {exc}',
        )

    _persist_run_log(
        log_path, argv, cwd, proc.stdout, proc.stderr,
        exit_code=proc.returncode, timed_out=False,
    )
    return CommandResult(
        description=description,
        argv=argv,
        cwd=str(cwd),
        exit_code=proc.returncode,
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr),
        timed_out=False,
        error=None,
    )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _persist_run_log(
    log_path: pathlib.Path,
    argv: list[str],
    cwd: pathlib.Path,
    stdout: str | None,
    stderr: str | None,
    exit_code: int | None,
    timed_out: bool,
) -> None:
    # stdout / stderr widened to Optional[str] because the
    # TimeoutExpired branch in _run_synchronous can legitimately
    # surface None (child killed before producing output). Coerce
    # locally so the on-disk log always has the same skeleton even
    # in the degenerate cases.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f'argv:      {argv}\n'
        f'cwd:       {cwd}\n'
        f'exit_code: {exit_code}\n'
        f'timed_out: {timed_out}\n'
        '----- stdout -----\n'
    )
    log_path.write_text(
        header + (stdout or '') + '\n----- stderr -----\n' + (stderr or ''),
        encoding='utf-8',
    )


# Held across the loop so we can terminate it before the next iteration.
_BackgroundProc = subprocess.Popen[bytes]


def _spawn_background(
    argv: list[str],
    cwd: pathlib.Path,
    env: dict[str, str],
    log_path: pathlib.Path,
) -> tuple[_BackgroundProc | None, str | None]:
    """Spawn a keeps_running=true launch command, redirecting output to a logfile.

    Returns (process, error). On error, process is None and error is a
    human-readable explanation suitable for feeding back to the model.

    We open the log file with `with` and close our parent-side handle
    immediately after Popen returns: the child has already inherited
    its own fd for stdout/stderr, so closing the parent copy is safe
    and avoids the dangling-handle pylint warning.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, 'wb') as log_file:
            # pylint: disable=consider-using-with
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
    except (OSError, ValueError) as exc:
        return None, f'failed to spawn: {exc}'
    return proc, None


def _terminate_background(proc: _BackgroundProc | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Healthcheck probe                                                           #
# --------------------------------------------------------------------------- #


# Defense-in-depth hard ceilings for the probe budget. The schema already
# bounds these via minimum/maximum, but the runner clamps a second time
# so an out-of-band path (manual plan, tests, future schema relaxation)
# cannot accidentally produce a 21-minute probe loop again.
_PROBE_MAX_ATTEMPTS_HARD_CAP: typing.Final[int] = 30
_PROBE_REQUEST_TIMEOUT_HARD_CAP: typing.Final[float] = 30.0
_PROBE_DELAY_HARD_CAP: typing.Final[float] = 15.0

# A TCP "actively refused" / ECONNREFUSED means the kernel got a RST in
# response to SYN -- i.e. *nothing is bound on that port*. Containers in
# a working state bind their port within seconds of starting; if we see
# this same error N times in a row after the pre_probe_delay, the launch
# command silently failed (container exited / crash-looped / wrong port
# binding) and waiting longer is just burning iteration budget. But for
# slow-booting dev servers (Next.js dev mode, Rails, Django) the port
# can take >1 minute to bind even though the container is healthy --
# the runner consults a launch introspector at trigger time to tell
# the two cases apart (see _build_launch_introspector).
_REFUSED_FAST_FAIL_AFTER: typing.Final[int] = 5
_REFUSED_MARKERS: typing.Final[tuple[str, ...]] = (
    'actively refused',          # Windows: WinError 10061
    'connection refused',         # Linux / macOS
    'ConnectionRefusedError',    # bare-socket repr
)


def _looks_like_connection_refused(error_text: str) -> bool:
    return any(marker in error_text for marker in _REFUSED_MARKERS)


@dataclasses.dataclass
class LaunchStateReport:
    """What the probe-side introspector saw about the launch's containers.

    `any_exited` is the disambiguator:
      - True  -> at least one of the launch's containers has exited /
                 dead. The launch silently failed; fast-fail now and
                 surface the log tail to the model.
      - False -> all launch containers are still 'running'. The port
                 not being bound yet just means the app is still
                 booting; reset the consecutive-refused counter and
                 keep probing within the model's max_attempts budget.
      - None  -> introspection itself failed (couldn't parse argv,
                 docker CLI errored, etc.). Preserve the
                 pre-introspector behavior: fast-fail. Safer than
                 keeping the loop alive on incomplete information.
    """
    any_exited: bool | None
    log_tail: str | None
    inspection_command: str | None


def _parse_launch_argv(argv: list[str]) -> dict[str, typing.Any] | None:
    """Best-effort extraction of "what did this launch command name?".

    Returns one of:
      {'mode': 'compose', 'files': [<compose-file>, ...]}
      {'mode': 'docker-run', 'name': <container-name>}
      None  (couldn't pattern-match)

    Intentionally minimal -- we only need enough to drive an
    introspection call against the same compose project / container
    name the launch used.
    """
    if len(argv) >= 2 and argv[0] == 'docker' and argv[1] == 'compose':
        files: list[str] = []
        i = 2
        while i < len(argv):
            if argv[i] in ('-f', '--file') and i + 1 < len(argv):
                files.append(argv[i + 1])
                i += 2
                continue
            i += 1
        return {'mode': 'compose', 'files': files}
    if argv and argv[0] == 'docker' and 'run' in argv:
        for i, tok in enumerate(argv):
            if tok == '--name' and i + 1 < len(argv):
                return {'mode': 'docker-run', 'name': argv[i + 1]}
    return None


def _docker_compose_introspect(
    compose_files: list[str],
    cwd: pathlib.Path,
) -> LaunchStateReport:
    base = ['docker', 'compose']
    for compose_file in compose_files:
        base.extend(['-f', compose_file])
    ps_argv = base + ['ps', '-a', '--format', 'json']
    cmd_repr = ' '.join(ps_argv)
    try:
        proc = subprocess.run(
            ps_argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return LaunchStateReport(
            any_exited=None, log_tail=None,
            inspection_command=f'{cmd_repr} -> {exc}',
        )
    if proc.returncode != 0:
        return LaunchStateReport(
            any_exited=None, log_tail=None,
            inspection_command=f'{cmd_repr} -> exit {proc.returncode}',
        )
    stdout = (proc.stdout or '').strip()
    if not stdout:
        return LaunchStateReport(
            any_exited=False, log_tail=None, inspection_command=cmd_repr,
        )
    try:
        if stdout.startswith('['):
            entries = json.loads(stdout)
        else:
            entries = [
                json.loads(line) for line in stdout.splitlines()
                if line.strip()
            ]
    except json.JSONDecodeError:
        return LaunchStateReport(
            any_exited=None, log_tail=None,
            inspection_command=f'{cmd_repr} -> non-JSON output',
        )
    exited: list[str] = []
    for entry in entries:
        state = (entry.get('State') or '').lower()
        if state in ('exited', 'dead', 'removing'):
            exited.append(
                entry.get('Service') or entry.get('Name') or '<?>',
            )
    if not exited:
        return LaunchStateReport(
            any_exited=False, log_tail=None, inspection_command=cmd_repr,
        )
    log_argv = base + ['logs', '--tail=80'] + exited
    try:
        log_proc = subprocess.run(
            log_argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        log_tail = (log_proc.stdout or '') + (log_proc.stderr or '')
    except (subprocess.SubprocessError, OSError) as exc:
        log_tail = f'(could not collect logs: {exc})'
    return LaunchStateReport(
        any_exited=True,
        log_tail=_tail(log_tail, max_bytes=4096),
        inspection_command=cmd_repr,
    )


def _docker_run_introspect(name: str) -> LaunchStateReport:
    inspect_argv = [
        'docker', 'inspect', '--format', '{{.State.Status}}', name,
    ]
    cmd_repr = ' '.join(inspect_argv)
    try:
        proc = subprocess.run(
            inspect_argv,
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return LaunchStateReport(
            any_exited=None, log_tail=None,
            inspection_command=f'{cmd_repr} -> {exc}',
        )
    if proc.returncode != 0:
        return LaunchStateReport(
            any_exited=None, log_tail=None,
            inspection_command=f'{cmd_repr} -> exit {proc.returncode}',
        )
    status = (proc.stdout or '').strip().lower()
    if status not in ('exited', 'dead', 'removing'):
        return LaunchStateReport(
            any_exited=False, log_tail=None, inspection_command=cmd_repr,
        )
    log_argv = ['docker', 'logs', '--tail=80', name]
    try:
        log_proc = subprocess.run(
            log_argv,
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        log_tail = (log_proc.stdout or '') + (log_proc.stderr or '')
    except (subprocess.SubprocessError, OSError) as exc:
        log_tail = f'(could not collect logs: {exc})'
    return LaunchStateReport(
        any_exited=True,
        log_tail=_tail(log_tail, max_bytes=4096),
        inspection_command=cmd_repr,
    )


def _build_launch_introspector(
    argv: list[str],
    cwd: pathlib.Path,
) -> typing.Callable[[], LaunchStateReport] | None:
    """Return a zero-arg closure the probe can call at fast-fail time.

    Returns None if we can't introspect the launch (which the probe
    treats as "preserve the old fast-fail behavior"). Parsing is
    deliberately conservative -- a launch shape we don't recognize
    is better treated as "introspection unavailable" than handed a
    confidently-wrong report.
    """
    parsed = _parse_launch_argv(argv)
    if parsed is None:
        return None
    if parsed['mode'] == 'compose':
        files = parsed['files']
        return lambda: _docker_compose_introspect(files, cwd)
    if parsed['mode'] == 'docker-run':
        name = parsed['name']
        return lambda: _docker_run_introspect(name)
    return None


# pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-arguments,too-many-positional-arguments
def _probe(
    healthcheck: dict[str, typing.Any],
    pre_probe_delay: float,
    introspect: typing.Callable[[], LaunchStateReport] | None = None,
) -> ProbeResult:
    url = healthcheck['url']
    method = healthcheck.get('method', 'GET').upper()
    expected = list(healthcheck.get('expected_status_codes', [200]))
    request_timeout = min(
        _PROBE_REQUEST_TIMEOUT_HARD_CAP,
        max(1.0, float(healthcheck.get('request_timeout_seconds', 5))),
    )
    max_attempts = min(
        _PROBE_MAX_ATTEMPTS_HARD_CAP,
        max(1, int(healthcheck.get('max_attempts', 10))),
    )
    delay = min(
        _PROBE_DELAY_HARD_CAP,
        max(0.0, float(healthcheck.get('delay_between_attempts_seconds', 2))),
    )

    if pre_probe_delay > 0:
        logging.info('[ launch ] sleeping %.1fs before first healthcheck probe', pre_probe_delay)
        time.sleep(pre_probe_delay)

    last_status: int | None = None
    last_error: str | None = None
    last_body_preview: str | None = None
    consecutive_refused = 0

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, timeout=request_timeout)
        except requests.RequestException as exc:
            last_status = None
            last_error = str(exc)
            logging.debug('[ launch ] probe %s/%s: %s', attempt, max_attempts, exc)
            if _looks_like_connection_refused(last_error):
                consecutive_refused += 1
                if consecutive_refused >= _REFUSED_FAST_FAIL_AFTER:
                    # Same RST N times in a row -> either the launch
                    # silently failed (container exited / crashed) OR
                    # the container is up but the app inside hasn't
                    # bound the port yet (Next.js dev mode, Rails
                    # boot, etc. can take >1min on slow workspaces).
                    # We ask the introspector to disambiguate before
                    # deciding whether to fast-fail or keep probing.
                    report = introspect() if introspect else None
                    if report is not None and report.any_exited is False:
                        logging.info(
                            '[ launch ] %d consecutive refused, but '
                            'launch containers are still running per '
                            '`%s` -- continuing to probe (port may '
                            'still be binding)',
                            consecutive_refused,
                            report.inspection_command,
                        )
                        consecutive_refused = 0
                        # Fall through to the inter-attempt sleep below.
                    else:
                        enriched_parts = [
                            f'connection refused {consecutive_refused} '
                            f'times in a row at {url}; the launch_command '
                            'appears to have failed silently (container '
                            'exited, crash-looped, or did not publish '
                            'the host port).',
                        ]
                        if report is not None:
                            enriched_parts.append(
                                f'Introspection ({report.inspection_command}): '
                                f'any_exited={report.any_exited}'
                            )
                            if report.log_tail:
                                enriched_parts.append(
                                    'Container log tail:\n' + report.log_tail,
                                )
                        enriched_parts.append(f'Last error: {last_error}')
                        enriched = '\n\n'.join(enriched_parts)
                        logging.info(
                            '[ launch ] probe fast-fail after %d consecutive '
                            'refused connections', consecutive_refused,
                        )
                        return ProbeResult(
                            url=url,
                            last_status=None,
                            expected_status_codes=expected,
                            attempts=attempt,
                            error=enriched,
                            response_body_preview=None,
                        )
            else:
                consecutive_refused = 0
        else:
            consecutive_refused = 0
            last_status = resp.status_code
            last_error = None
            try:
                preview = resp.text[:200]
            except (UnicodeDecodeError, AttributeError):
                preview = None
            last_body_preview = preview
            if resp.status_code in expected:
                logging.info(
                    '[ launch ] probe ok: %s %s -> %s',
                    method, url, resp.status_code,
                )
                return ProbeResult(
                    url=url,
                    last_status=resp.status_code,
                    expected_status_codes=expected,
                    attempts=attempt,
                    error=None,
                    response_body_preview=preview,
                )
            logging.debug(
                '[ launch ] probe %s/%s: status=%s (want one of %s)',
                attempt, max_attempts, resp.status_code, expected,
            )
        if attempt < max_attempts:
            time.sleep(delay)

    return ProbeResult(
        url=url,
        last_status=last_status,
        expected_status_codes=expected,
        attempts=max_attempts,
        error=last_error,
        response_body_preview=last_body_preview,
    )


# --------------------------------------------------------------------------- #
# Plan application                                                            #
# --------------------------------------------------------------------------- #


def _apply_plan_env(
    target_dir: pathlib.Path,
    plan: dict[str, typing.Any],
) -> tuple[dict[str, str], str | None]:
    """Merge plan.env onto os.environ, refusing to overwrite PATH-style keys."""
    env = os.environ.copy()
    env.setdefault('DHSCANNER_LAUNCH_TARGET_DIR', str(target_dir))
    for entry in plan.get('env', []) or []:
        name = entry['name']
        value = entry['value']
        # Letting the model overwrite PATH would let one bad iteration
        # turn the next `docker` lookup into a hard failure for reasons
        # the model can't easily diagnose from feedback.
        if name.upper() in {'PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH'}:
            return env, f'plan tried to overwrite reserved env var: {name}'
        env[name] = value
    return env, None


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _run_command_list(
    commands: list[dict[str, typing.Any]],
    target_dir: pathlib.Path,
    env: dict[str, str],
    iter_log_dir: pathlib.Path,
    phase: str,
    must_succeed: bool,
) -> tuple[list[CommandResult], str | None]:
    """Execute a list of commands in order.

    Returns (results, first_failure_message). When ``must_succeed`` and
    a command fails, we stop early and the caller is expected to feed
    the failure back to the model.
    """
    results: list[CommandResult] = []
    for i, cmd in enumerate(commands):
        log_path = iter_log_dir / f'{phase}-{i:02d}.log'
        argv = list(cmd['argv'])
        argv_err = _validate_argv(argv)
        if argv_err:
            results.append(CommandResult(
                description=cmd.get('description', ''),
                argv=argv,
                cwd=str(target_dir),
                exit_code=None,
                stdout_tail='',
                stderr_tail='',
                timed_out=False,
                error=argv_err,
            ))
            if must_succeed:
                return results, f'{phase}#{i}: {argv_err}'
            continue
        cwd_or_err = _validate_relative_cwd(target_dir, cmd.get('cwd'))
        if isinstance(cwd_or_err, str):
            results.append(CommandResult(
                description=cmd.get('description', ''),
                argv=argv,
                cwd=str(target_dir),
                exit_code=None,
                stdout_tail='',
                stderr_tail='',
                timed_out=False,
                error=cwd_or_err,
            ))
            if must_succeed:
                return results, f'{phase}#{i}: {cwd_or_err}'
            continue
        result = _run_synchronous(
            description=cmd.get('description', ''),
            argv=argv,
            cwd=cwd_or_err,
            env=env,
            timeout_seconds=int(cmd.get('timeout_seconds', 60)),
            log_path=log_path,
        )
        results.append(result)
        if must_succeed and (result.exit_code != 0 or result.timed_out or result.error):
            why = result.error or (
                'timed out' if result.timed_out
                else f'exit_code={result.exit_code}'
            )
            return results, f'{phase}#{i}: {why}'
    return results, None


# --------------------------------------------------------------------------- #
# Feedback construction                                                       #
# --------------------------------------------------------------------------- #


def _command_result_brief(result: CommandResult) -> dict[str, typing.Any]:
    return {
        'description': result.description,
        'argv': result.argv,
        'cwd': result.cwd,
        'exit_code': result.exit_code,
        'timed_out': result.timed_out,
        'error': result.error,
        'stdout_tail': result.stdout_tail,
        'stderr_tail': result.stderr_tail,
    }


def _probe_result_brief(probe: ProbeResult) -> dict[str, typing.Any]:
    return {
        'url': probe.url,
        'method': 'GET',
        'last_status': probe.last_status,
        'expected_status_codes': probe.expected_status_codes,
        'attempts': probe.attempts,
        'error': probe.error,
        'response_body_preview': probe.response_body_preview,
    }


# --------------------------------------------------------------------------- #
# OpenAI client                                                               #
# --------------------------------------------------------------------------- #


def _maybe_load_dotenv() -> None:
    # Same convention as dhscanner/dhscanner.1.parsers/agent_loop.py:
    # a .env in the agent dir is honored if python-dotenv is installed,
    # otherwise we silently fall through to os.environ. The lazy import
    # keeps `import agent.launcher` cheap (and importable from tests
    # that don't actually call into the model).
    # pylint: disable=import-outside-toplevel
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
    except ImportError:
        return
    load_dotenv(HERE / '.env')


def _ensure_openai_key() -> None:
    if not os.environ.get('OPENAI_API_KEY'):
        raise SystemExit(
            'OPENAI_API_KEY not set. Export it or place it in agent/.env'
        )


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
def _ask_for_plan(
    model: str,
    timeout: float,
    target_dir: pathlib.Path,
    tree: list[str],
    readme: tuple[str, str] | None,
    manifests: dict[str, str],
    history: list[dict[str, typing.Any]],
) -> tuple[dict[str, typing.Any], list[dict[str, typing.Any]]]:
    """Drive the planning round as a tool-using OpenAI loop.

    Each turn the model may either (a) call one or more of the
    plan-time tools (`read_file`, `list_dir`, `grep`), which the runner
    dispatches against target_dir and feeds back, or (b) return its
    final LaunchPlan as JSON conforming to LAUNCH_PLAN_SCHEMA. The loop
    is hard-capped at MAX_TOOL_CALLS_PER_PLAN to bound cost and to keep
    a runaway exploration loop from blocking the iteration.

    Returns (plan, transcript) where transcript is a list of
    {name, arguments, result_preview, error?} dicts captured for the
    audit trail. The caller persists the transcript next to
    iter-NN/plan.json so we can debug why a plan was/wasn't accepted.
    """
    # Lazy import so `import agent.launcher` stays cheap (and works in
    # environments without the openai SDK -- e.g. unit tests that only
    # exercise the validation / probe logic).
    # pylint: disable=import-outside-toplevel
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            'openai package not installed. Run: pip install -r requirements.txt'
        ) from exc

    user_prompt = _build_user_prompt(target_dir, tree, readme, manifests, history)

    client = OpenAI(timeout=timeout)
    messages: list[dict[str, typing.Any]] = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]
    transcript: list[dict[str, typing.Any]] = []
    tool_calls_used = 0

    for _round in range(MAX_TOOL_CALLS_PER_PLAN + 1):
        # Once we've exhausted the budget, do one final call WITHOUT
        # tools to force the model to commit to a plan with whatever
        # context it already collected. Same response_format on both
        # branches; only the tools list differs.
        budget_exhausted = tool_calls_used >= MAX_TOOL_CALLS_PER_PLAN
        kwargs: dict[str, typing.Any] = {
            'model': model,
            'messages': messages,
            'response_format': {
                'type': 'json_schema',
                'json_schema': LAUNCH_PLAN_SCHEMA,
            },
        }
        if not budget_exhausted:
            kwargs['tools'] = LAUNCH_PLAN_TOOLS

        # The openai SDK types `messages` as a union of TypedDicts (one
        # per role) whose discriminator is the literal `role` field.
        # mypy can't narrow `dict[str, Any]` to those TypedDicts, but
        # they're shape-equivalent at runtime.
        resp = client.chat.completions.create(  # type: ignore[call-overload]
            **kwargs,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, 'tool_calls', None) or []

        if not tool_calls:
            content = msg.content or '{}'
            return json.loads(content), transcript

        # Replay the assistant turn (must include tool_calls so the
        # subsequent role='tool' messages have something to refer to).
        messages.append({
            'role': 'assistant',
            'content': msg.content or '',
            'tool_calls': [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.function.name,
                        'arguments': tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            tool_calls_used += 1
            name = tc.function.name
            raw_args = tc.function.arguments or '{}'
            try:
                result_text = _dispatch_tool_call(name, raw_args, target_dir)
            except Exception as exc:  # pylint: disable=broad-except
                # Defensive: a bug in a tool impl should NOT crash the
                # iteration loop -- surface it to the model as a tool
                # error so it can try a different approach.
                result_text = f'ERROR: tool {name!r} raised: {exc}'
            # Cap each tool result independently of the per-tool caps
                # above, in case a tool returned more than expected.
            if len(result_text) > MAX_TOOL_OUTPUT_BYTES * 2:
                result_text = (
                    result_text[: MAX_TOOL_OUTPUT_BYTES * 2]
                    + '\n... <result further truncated by dispatcher>'
                )
            messages.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': result_text,
            })
            transcript.append({
                'name': name,
                'arguments': raw_args,
                'result_preview': _tail(result_text, max_bytes=1200),
                'result_bytes': len(result_text),
                'budget_used': tool_calls_used,
            })
            logging.info(
                '[ launcher ] tool=%s args=%s -> %d bytes (budget %d/%d)',
                name, raw_args, len(result_text), tool_calls_used,
                MAX_TOOL_CALLS_PER_PLAN,
            )

        if budget_exhausted:
            # Shouldn't happen -- we sent the request without tools so
            # the model can't have emitted tool_calls -- but bail
            # defensively rather than infinite-loop.
            raise SystemExit(
                'planning round exhausted tool budget and the model '
                'still tried to call tools; aborting'
            )

    # Loop exited without producing a final plan AND without crashing
    # on the budget check -- means MAX_TOOL_CALLS_PER_PLAN + 1 was
    # itself exhausted. This is unreachable given the budget check
    # above, but kept as a tripwire.
    raise SystemExit(
        'planning round did not converge within '
        f'{MAX_TOOL_CALLS_PER_PLAN} tool calls'
    )


def _build_user_prompt(
    target_dir: pathlib.Path,
    tree: list[str],
    readme: tuple[str, str] | None,
    manifests: dict[str, str],
    history: list[dict[str, typing.Any]],
) -> str:
    pieces: list[str] = []
    pieces.append('## Target')
    pieces.append('')
    pieces.append(f'absolute path: {target_dir}')
    pieces.append(f'host os:       {platform.system()} ({platform.release()})')
    pieces.append(f'python:        {sys.executable}')
    pieces.append('')
    pieces.append('## Repo tree (depth-limited, breadth-first)')
    pieces.append('')
    pieces.append('```')
    pieces.extend(tree[:MAX_TREE_ENTRIES])
    if len(tree) >= MAX_TREE_ENTRIES:
        pieces.append(f'... (showing first {MAX_TREE_ENTRIES} entries)')
    pieces.append('```')
    pieces.append('')
    if readme is not None:
        readme_name, readme_text = readme
        pieces.append(f'## {readme_name}')
        pieces.append('')
        pieces.append('```')
        pieces.append(readme_text)
        pieces.append('```')
        pieces.append('')
    if manifests:
        pieces.append('## Manifests / build descriptors')
        pieces.append('')
        for name, body in manifests.items():
            pieces.append(f'### {name}')
            pieces.append('')
            pieces.append('```')
            pieces.append(body)
            pieces.append('```')
            pieces.append('')
    if history:
        pieces.append('## Previous iterations')
        pieces.append('')
        pieces.append(
            'Each entry shows the plan you produced, what happened when '
            'the runner applied it, and (where applicable) the failure '
            'reason. Read these before changing your next plan.'
        )
        pieces.append('')
        pieces.append('```json')
        pieces.append(json.dumps(history, indent=2, ensure_ascii=False))
        pieces.append('```')
        pieces.append('')
    pieces.append('## Task')
    pieces.append('')
    pieces.append(
        'Return a LaunchPlan JSON. Read the rules in the system prompt '
        'before answering. If a previous iteration is shown, your new '
        'plan should fix the specific failure surfaced there.'
    )
    return '\n'.join(pieces)


# --------------------------------------------------------------------------- #
# One iteration                                                               #
# --------------------------------------------------------------------------- #


# pylint: disable=too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
def _run_iteration(
    iteration: int,
    plan: dict[str, typing.Any],
    target_dir: pathlib.Path,
    iter_log_dir: pathlib.Path,
    pre_probe_delay: float,
    background_holder: dict[str, _BackgroundProc | None],
) -> IterationOutcome:
    iter_log_dir.mkdir(parents=True, exist_ok=True)
    (iter_log_dir / 'plan.json').write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8',
    )

    if plan.get('give_up'):
        return IterationOutcome(
            iteration=iteration,
            plan=plan,
            prep_results=[],
            launch_result=None,
            probe_result=None,
            accepted=False,
            rejection_reason=f'model gave up: {plan.get("give_up_reason", "")}',
        )

    env, env_err = _apply_plan_env(target_dir, plan)
    if env_err is not None:
        return IterationOutcome(
            iteration=iteration,
            plan=plan,
            prep_results=[],
            launch_result=None,
            probe_result=None,
            accepted=False,
            rejection_reason=env_err,
        )

    prep_results, prep_failure = _run_command_list(
        commands=plan.get('prep_commands', []) or [],
        target_dir=target_dir,
        env=env,
        iter_log_dir=iter_log_dir,
        phase='prep',
        must_succeed=True,
    )
    if prep_failure is not None:
        return IterationOutcome(
            iteration=iteration,
            plan=plan,
            prep_results=prep_results,
            launch_result=None,
            probe_result=None,
            accepted=False,
            rejection_reason=f'prep_commands failed: {prep_failure}',
        )

    launch_cmd = plan.get('launch_command')
    launch_result: CommandResult | None = None
    if launch_cmd is not None:
        argv = list(launch_cmd['argv'])
        # Two-stage validation: first the cheap generic banlist (sudo,
        # empty argv), then the Docker-only constraint. They are kept
        # separate so the rejection message back to the model is
        # specific to the rule it violated.
        argv_err = _validate_argv(argv) or _validate_launch_argv(argv)
        if argv_err is not None:
            return IterationOutcome(
                iteration=iteration,
                plan=plan,
                prep_results=prep_results,
                launch_result=CommandResult(
                    description=launch_cmd.get('description', ''),
                    argv=argv,
                    cwd=str(target_dir),
                    exit_code=None,
                    stdout_tail='',
                    stderr_tail='',
                    timed_out=False,
                    error=argv_err,
                ),
                probe_result=None,
                accepted=False,
                rejection_reason=f'launch_command rejected: {argv_err}',
            )
        cwd_or_err = _validate_relative_cwd(target_dir, launch_cmd.get('cwd'))
        if isinstance(cwd_or_err, str):
            return IterationOutcome(
                iteration=iteration,
                plan=plan,
                prep_results=prep_results,
                launch_result=CommandResult(
                    description=launch_cmd.get('description', ''),
                    argv=argv,
                    cwd=str(target_dir),
                    exit_code=None,
                    stdout_tail='',
                    stderr_tail='',
                    timed_out=False,
                    error=cwd_or_err,
                ),
                probe_result=None,
                accepted=False,
                rejection_reason=f'launch_command rejected: {cwd_or_err}',
            )
        launch_log = iter_log_dir / 'launch.log'
        if launch_cmd.get('keeps_running'):
            proc, err = _spawn_background(argv, cwd_or_err, env, launch_log)
            if proc is None:
                launch_result = CommandResult(
                    description=launch_cmd.get('description', ''),
                    argv=argv,
                    cwd=str(cwd_or_err),
                    exit_code=None,
                    stdout_tail='',
                    stderr_tail='',
                    timed_out=False,
                    error=err,
                )
                return IterationOutcome(
                    iteration=iteration,
                    plan=plan,
                    prep_results=prep_results,
                    launch_result=launch_result,
                    probe_result=None,
                    accepted=False,
                    rejection_reason=f'launch spawn failed: {err}',
                )
            background_holder['proc'] = proc
            launch_result = CommandResult(
                description=launch_cmd.get('description', ''),
                argv=argv,
                cwd=str(cwd_or_err),
                exit_code=None,
                stdout_tail='',
                stderr_tail='',
                timed_out=False,
                error=None,
            )
        else:
            launch_result = _run_synchronous(
                description=launch_cmd.get('description', ''),
                argv=argv,
                cwd=cwd_or_err,
                env=env,
                timeout_seconds=int(launch_cmd.get('timeout_seconds', 120)),
                log_path=launch_log,
            )
            if (
                launch_result.exit_code != 0
                or launch_result.timed_out
                or launch_result.error
            ):
                why = launch_result.error or (
                    'timed out' if launch_result.timed_out
                    else f'exit_code={launch_result.exit_code}'
                )
                return IterationOutcome(
                    iteration=iteration,
                    plan=plan,
                    prep_results=prep_results,
                    launch_result=launch_result,
                    probe_result=None,
                    accepted=False,
                    rejection_reason=f'launch_command failed: {why}',
                )

    healthcheck = plan.get('healthcheck')
    if healthcheck is None:
        return IterationOutcome(
            iteration=iteration,
            plan=plan,
            prep_results=prep_results,
            launch_result=launch_result,
            probe_result=None,
            accepted=False,
            rejection_reason='healthcheck is required for acceptance',
        )
    if (url_err := _validate_healthcheck_url(healthcheck['url'])) is not None:
        return IterationOutcome(
            iteration=iteration,
            plan=plan,
            prep_results=prep_results,
            launch_result=launch_result,
            probe_result=None,
            accepted=False,
            rejection_reason=f'healthcheck rejected: {url_err}',
        )

    # Build an introspector once per iteration: the probe asks it
    # "are the launch containers still running?" before fast-failing
    # on consecutive connection-refused. None means "I don't know how
    # to introspect this launch shape" -- the probe then preserves
    # the original fast-fail behavior.
    introspect: typing.Callable[[], LaunchStateReport] | None = None
    if launch_result is not None and launch_result.argv:
        introspect_cwd = pathlib.Path(launch_result.cwd or str(target_dir))
        introspect = _build_launch_introspector(
            launch_result.argv, introspect_cwd,
        )

    probe = _probe(healthcheck, pre_probe_delay, introspect=introspect)
    accepted = probe.ok
    rejection: str | None = None
    if not accepted:
        if probe.last_status is None:
            rejection = f'healthcheck never responded: {probe.error}'
        else:
            rejection = (
                f'healthcheck got status {probe.last_status} '
                f'(want one of {probe.expected_status_codes})'
            )

    return IterationOutcome(
        iteration=iteration,
        plan=plan,
        prep_results=prep_results,
        launch_result=launch_result,
        probe_result=probe,
        accepted=accepted,
        rejection_reason=rejection,
    )


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def _outcome_to_history_entry(outcome: IterationOutcome) -> dict[str, typing.Any]:
    return {
        'iteration': outcome.iteration,
        'plan_summary': outcome.plan.get('summary', ''),
        'plan': outcome.plan,
        'prep_results': [_command_result_brief(r) for r in outcome.prep_results],
        'launch_result': (
            _command_result_brief(outcome.launch_result)
            if outcome.launch_result is not None else None
        ),
        'probe_result': (
            _probe_result_brief(outcome.probe_result)
            if outcome.probe_result is not None else None
        ),
        'accepted': outcome.accepted,
        'rejection_reason': outcome.rejection_reason,
    }


def _run_cleanup(
    plan: dict[str, typing.Any],
    target_dir: pathlib.Path,
    iter_log_dir: pathlib.Path,
) -> None:
    env, env_err = _apply_plan_env(target_dir, plan)
    if env_err is not None:
        logging.warning('[ launch ] cleanup env rejected: %s', env_err)
        return
    _run_command_list(
        commands=plan.get('cleanup_commands', []) or [],
        target_dir=target_dir,
        env=env,
        iter_log_dir=iter_log_dir,
        phase='cleanup',
        must_succeed=False,
    )


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def launch(parsed_args: CliLaunchLocalAppArgparse) -> int:
    """Entry point invoked by cli.py's @main.register dispatch."""
    _maybe_load_dotenv()
    # --dry-run still calls the model (that's the whole point: see the
    # plan it would produce). The key check stays unconditional so we
    # fail fast with a friendly error instead of letting a 401 surface
    # later via the openai SDK with less context.
    _ensure_openai_key()

    target_dir = parsed_args.target_dir.resolve()
    if not target_dir.is_dir():
        logging.error('[ launch ] target_dir is not a directory: %s', target_dir)
        return 1

    logging.info('[ launch ] target_dir: %s', target_dir)
    logging.info('[ launch ] collecting repo context...')
    tree = _collect_tree(target_dir, MAX_TREE_ENTRIES)
    readme = _collect_readme(target_dir)
    manifests = _collect_manifests(target_dir)
    logging.info(
        '[ launch ] context: %d tree entries, readme=%s, manifests=%s',
        len(tree),
        readme[0] if readme else 'none',
        sorted(manifests.keys()) or 'none',
    )

    model = parsed_args.model or os.environ.get('OPENAI_MODEL') or DEFAULT_MODEL
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    run_log_dir = LAUNCH_LOGS_ROOT / target_dir.name / timestamp
    run_log_dir.mkdir(parents=True, exist_ok=True)
    logging.info('[ launch ] per-iteration logs: %s', run_log_dir)

    history: list[dict[str, typing.Any]] = []
    last_accepted_plan: dict[str, typing.Any] | None = None
    background_holder: dict[str, _BackgroundProc | None] = {'proc': None}

    try:
        for iteration in range(1, parsed_args.max_iterations + 1):
            logging.info(
                '[ launch ] === iteration %s / %s ===',
                iteration, parsed_args.max_iterations,
            )
            logging.info('[ launch ] asking %s for a plan...', model)
            try:
                plan, tool_transcript = _ask_for_plan(
                    model=model,
                    timeout=parsed_args.openai_timeout,
                    target_dir=target_dir,
                    tree=tree,
                    readme=readme,
                    manifests=manifests,
                    history=history,
                )
            # We deliberately catch broadly here: the openai SDK raises
            # many different exception types (auth, rate-limit, network,
            # invalid_response) and the model-call site is the one place
            # where a transient error is cheap to surface and retry next
            # iteration. Re-raising would discard partial progress.
            # pylint: disable=broad-except
            except Exception as exc:
                logging.error('[ launch ] openai call failed: %s', exc)
                return 1

            summary = plan.get('summary', '(no summary)')
            logging.info(
                '[ launch ] plan: %s (used %d tool call(s) to gather context)',
                summary, len(tool_transcript),
            )

            if parsed_args.dry_run:
                logging.info('[ launch ] dry-run: not executing the plan')
                logging.info('[ launch ] plan JSON:\n%s', json.dumps(plan, indent=2))
                return 0

            iter_log_dir = run_log_dir / f'iter-{iteration:02d}'
            iter_log_dir.mkdir(parents=True, exist_ok=True)
            # Persist the tool transcript next to the plan so post-mortem
            # debugging shows *what the model looked at* before drafting
            # this plan -- the most valuable signal when an iteration
            # fails on something the prompt context didn't surface.
            (iter_log_dir / 'tool_transcript.json').write_text(
                json.dumps(tool_transcript, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
            outcome = _run_iteration(
                iteration=iteration,
                plan=plan,
                target_dir=target_dir,
                iter_log_dir=iter_log_dir,
                pre_probe_delay=parsed_args.probe_delay,
                background_holder=background_holder,
            )
            history.append(_outcome_to_history_entry(outcome))
            (iter_log_dir / 'outcome.json').write_text(
                json.dumps(history[-1], indent=2, ensure_ascii=False),
                encoding='utf-8',
            )

            if outcome.accepted:
                last_accepted_plan = plan
                logging.info(
                    '[ launch ] ACCEPTED on iteration %s: %s',
                    iteration, summary,
                )
                if outcome.probe_result is not None:
                    logging.info(
                        '[ launch ] healthcheck %s -> %s',
                        outcome.probe_result.url,
                        outcome.probe_result.last_status,
                    )
                break

            logging.warning(
                '[ launch ] REJECTED on iteration %s: %s',
                iteration, outcome.rejection_reason,
            )

            # Between iterations: kill anything we spawned (background
            # launch) and run the plan's own cleanup so the next plan
            # starts from a clean slate (e.g. `docker compose down`).
            _terminate_background(background_holder['proc'])
            background_holder['proc'] = None
            _run_cleanup(plan, target_dir, iter_log_dir)

        else:
            logging.error(
                '[ launch ] exhausted %s iterations without a working plan',
                parsed_args.max_iterations,
            )
            _terminate_background(background_holder['proc'])
            return 1

        if parsed_args.teardown_on_exit and last_accepted_plan is not None:
            logging.info('[ launch ] --teardown-on-exit: running cleanup...')
            _terminate_background(background_holder['proc'])
            background_holder['proc'] = None
            _run_cleanup(last_accepted_plan, target_dir, run_log_dir / 'teardown')
        elif background_holder['proc'] is not None:
            logging.info(
                '[ launch ] leaving foreground app running (pid=%s); '
                'use --teardown-on-exit next time to stop it on exit',
                background_holder['proc'].pid,
            )

        return 0

    except KeyboardInterrupt:
        logging.warning('[ launch ] interrupted; tearing down...')
        _terminate_background(background_holder['proc'])
        if last_accepted_plan is not None:
            _run_cleanup(last_accepted_plan, target_dir, run_log_dir / 'teardown')
        return 130
