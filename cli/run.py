from __future__ import annotations

import os
import http
import math
import json
import time
import typing
import pathlib
import asyncio
import functools
import subprocess
import logging
import aiofiles
import aiohttp
import requests
from cli.argparse_wrapper import (
    CliArgparse,
    CliRunArgparse,
    CliManageArgparse,
    CliLaunchLocalAppArgparse,
)
from agent import launcher as local_app_launcher
from cli import logger as cli_logger

LOCALHOST: typing.Final[str] = 'http://localhost'
PORT: typing.Final[int] = 8000

SUFFIXES: typing.Final[set[str]] = {
    'py', 'ts', 'js', 'php', 'rb', 'java', 'cs', 'go', 'yaml', 'yml'
}

# Third-party dependency trees — skip entirely during collection.
IGNORED_3RD_PARTY_DIRS: typing.Final[set[str]] = {
    'vendor',
    'node_modules',
    'site_packages',
    'site-packages',
}

MAX_ATTEMPTS_CONNECTING_TO_SERVER = 10
UPLOAD_BATCH_SIZE = 100
MAX_NUM_CHECKS = 200
NUM_SECONDS_BETEEN_STEP_CHECK = 5

HTTPS_PORT: typing.Final[int] = 443
HTTPS_PREFIX: typing.Final[str] = 'https://'
DOT_GIT_SUFFIX: typing.Final[str] = '.git'
LEN_HTTPS_PREFIX: typing.Final[int] = len(HTTPS_PREFIX)
LEN_DOT_GIT_SUFFIX: typing.Final[int] = len(DOT_GIT_SUFFIX)
GIT_AT_PREFIX: typing.Final[str] = 'git@'
LEN_GIT_AT_PREFIX: typing.Final[int] = len(GIT_AT_PREFIX)

# Install the colorized DEBUG-level stdout handler. DEBUG-default is
# intentional: the upload loop demotes its high-frequency progress lines
# to DEBUG and relies on the cyan-tinted level name to fade them out
# visually rather than filtering them out entirely.
cli_logger.configure()

# pylint: disable=too-many-return-statements
def relevant(filename: pathlib.Path) -> bool:
    if filename.name == 'go.mod':
        return True

    if filename.suffix.lstrip('.') not in SUFFIXES:
        return False

    resolved = filename.resolve()
    parts = resolved.parts
    if IGNORED_3RD_PARTY_DIRS.intersection(parts):
        return False

    name = str(resolved)
    if 'test' in parts:
        return False

    if 'tests' in parts:
        return False

    if '.test.' in name:
        return False

    if name.endswith('.d.ts'):
        return False

    return True

def collect_relevant_files(scan_dirname: pathlib.Path) -> list[pathlib.Path]:

    filenames = []
    for root, dirs, files in os.walk(scan_dirname):
        dirs[:] = [d for d in dirs if d not in IGNORED_3RD_PARTY_DIRS]
        for filename in files:
            abspath_filename = pathlib.Path(root) / filename
            if relevant(abspath_filename):
                filenames.append(abspath_filename.relative_to(scan_dirname))

    if filenames:
        logging.info('[ step 2 ] collected %s files', len(filenames))
    else:
        logging.warning('[ step 2 ] no files were collected')

    return filenames

def collect_directories_and_filenames(
    files: list[pathlib.Path]
) -> tuple[list[str], list[str]]:
    """
    Collect all directories containing source files and all filenames.
    Returns (directories, filenames) where:
    - directories: list of directory paths (as strings) that contain source files
    - filenames: list of all filenames (as strings) relative to the source directory root
    """
    directories_set: set[str] = set()
    filenames_list: list[str] = []

    for f in files:
        # Convert to string path relative to scan_dirname
        file_str = f.as_posix()
        filenames_list.append(file_str)

        # Get the directory containing this file
        file_dir = f.parent
        if file_dir != pathlib.Path('.'):
            dir_str = file_dir.as_posix()
            directories_set.add(dir_str)
        else:
            # File is in root, add empty string or '.' to represent root
            directories_set.add('')

    # Convert set to sorted list for consistent ordering
    directories_list = sorted(list(directories_set))

    return directories_list, filenames_list

# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def resolve_file_mappings(
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path]
) -> dict[str, list[dict[str, str]]]:
    """
    Resolve path alias mappings from tsconfig.json files.
    Returns a dict mapping each source file to its applicable (prefix, replacement) pairs.
    E.g. {"src/app/page.tsx": [{"from": "@/", "to": "src/"}]}
    """
    root = scan_dirname.resolve()

    # Collect all tsconfig.json files in the repo.
    tsconfigs: list[pathlib.Path] = []
    for dirpath, _, filenames in os.walk(root):
        if 'tsconfig.json' in filenames:
            tsconfigs.append(pathlib.Path(dirpath) / 'tsconfig.json')

    if not tsconfigs:
        return {}

    # Pre-compute normalized mappings for each tsconfig directory.
    # Entry format: (tsconfig_dir_abs, mappings)
    by_tsconfig: list[tuple[pathlib.Path, list[dict[str, str]]]] = []
    for tsconfig in tsconfigs:
        try:
            with tsconfig.open('r', encoding='utf-8') as fh:
                content = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue

        compiler_options = content.get('compilerOptions', {})
        if not isinstance(compiler_options, dict):
            continue

        paths = compiler_options.get('paths', {})
        if not isinstance(paths, dict):
            continue

        base_url_raw = compiler_options.get('baseUrl', '.')
        if not isinstance(base_url_raw, str):
            base_url_raw = '.'

        tsconfig_dir = tsconfig.parent.resolve()
        base_dir = (tsconfig_dir / base_url_raw).resolve()

        mappings: list[dict[str, str]] = []
        for alias, targets in paths.items():
            if not isinstance(alias, str):
                continue
            if not isinstance(targets, list) or not targets:
                continue

            first_target = targets[0]
            if not isinstance(first_target, str):
                continue

            # Keep the alias prefix as the "actual prefix".
            # Examples:
            # - "@src/*" -> "@src"
            # - "@/apps/*" -> "@/apps"
            from_prefix = alias
            if from_prefix.endswith('/*'):
                from_prefix = from_prefix[:-2]
            elif from_prefix.endswith('*'):
                from_prefix = from_prefix[:-1]
            from_prefix = from_prefix.rstrip('/')
            if not from_prefix:
                continue

            # Normalize target and resolve it against tsconfig baseUrl.
            # Then convert to project-root-relative path.
            target = first_target
            if target.endswith('/*'):
                target = target[:-2]
            elif target.endswith('*'):
                target = target[:-1]
            target = target.replace('\\', '/').strip()
            if not target:
                continue

            target_abs = pathlib.Path(target)
            if not target_abs.is_absolute():
                target_abs = (base_dir / target).resolve()

            try:
                target_rel = target_abs.relative_to(root).as_posix()
            except ValueError:
                # Ignore mappings that resolve outside project root.
                continue

            if target_rel == '.':
                target_rel = ''
            target_rel = target_rel.lstrip('./')

            mappings.append({'from': from_prefix, 'to': target_rel})

        if mappings:
            by_tsconfig.append((tsconfig_dir, mappings))

    if not by_tsconfig:
        return {}

    # Nearest tsconfig directory (deepest ancestor) wins for each file.
    by_tsconfig.sort(key=lambda item: len(item[0].parts), reverse=True)

    result: dict[str, list[dict[str, str]]] = {}
    for rel_file in files:
        abs_file = (root / rel_file).resolve()
        for tsconfig_dir, mappings in by_tsconfig:
            try:
                abs_file.relative_to(tsconfig_dir)
                result[rel_file.as_posix()] = mappings
                break
            except ValueError:
                continue

    return result

def create_job_id(APPROVED_URL: str, BEARER_TOKEN: str, parsed_args: CliArgparse) -> typing.Optional[str]:
    headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    url = f'{host}:{port}/api/{APPROVED_URL}/getjobid'
    response = requests.get(url, headers=headers)
    if response.status_code != http.HTTPStatus.OK:
        logging.error('failed to create job id: http status code %s', response.status_code)
        return None

    try:
        content = response.json()
        return content['job_id']
    except json.JSONDecodeError:
        logging.error('failed to return proper job id json response')
    except KeyError:
        logging.error('actual job id missing from json response')

    return None

def upload_url(APPROVED_URL: str, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/upload'

def upload_headers(
    BEARER_TOKEN: str,
    filename: str,
    gomod: typing.Optional[str],
    github_url: typing.Optional[str],
    path_mappings: typing.Optional[str] = None,
) -> dict:

    headers = {
        'Authorization': f'Bearer {BEARER_TOKEN}',
        'X-Path': filename,
        'Content-Type': 'application/octet-stream'
    }

    if gomod is not None:
        headers['X-Module-Name-Resolver-Go.mod'] = gomod
    if github_url is not None:
        headers['X-GitHub-URL'] = github_url
    if path_mappings is not None:
        headers['X-Path-Mappings'] = path_mappings

    return headers

def just_authroization_header(BEARER_TOKEN: str) -> dict:
    return {'Authorization': f'Bearer {BEARER_TOKEN}'}

def analyze_headers(BEARER_TOKEN: str) -> dict:
    return just_authroization_header(BEARER_TOKEN)

def status_headers(BEARER_TOKEN: str) -> dict:
    return just_authroization_header(BEARER_TOKEN)

async def check_response(response: aiohttp.ClientResponse, filename: str) -> bool:

    status = response.status
    if status != http.HTTPStatus.OK:
        logging.error('upload failed for %s http status: %s', filename, status)
        return False

    try:
        result = await response.json()
        if 'status' in result:
            if result['status'] == 'ok':
                return True
    except json.JSONDecodeError:
        logging.error('Invalid upload response for %s', filename)

    return False

# pylint: disable=too-many-arguments,too-many-positional-arguments
async def actual_upload(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    params: dict,
    scan_dirname: pathlib.Path,
    f: pathlib.Path,
) -> bool:

    try:
        async with aiofiles.open(scan_dirname / f, 'rb') as content:
            async with session.post(url, params=params, headers=headers, data=content) as response:
                return await check_response(response, f.name)
    except FileNotFoundError:
        return False

async def upload_single_file(
    session: aiohttp.ClientSession,
    job_id: str,
    scan_dirname: pathlib.Path,
    f: pathlib.Path,
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    gomod: typing.Optional[str],
    github_url: typing.Optional[str],
    path_mappings: typing.Optional[str],
    parsed_args: CliArgparse
) -> bool:

    params = {'job_id': job_id}
    url = upload_url(APPROVED_URL, parsed_args)
    headers = upload_headers(BEARER_TOKEN, f.as_posix(), gomod, github_url, path_mappings)
    return await actual_upload(session, url, headers, params, scan_dirname, f)

def extract_module_name_from(gomod: pathlib.Path) -> typing.Optional[str]:
    with gomod.open('r') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('module'):
                parts = stripped.split()
                if parts[0] == 'module':
                    if len(parts) == 2:
                        return parts[1]
    return None

def extract_github_url_from(scan_dirname: pathlib.Path) -> typing.Optional[str]:
    try:
        extract_github_url = subprocess.run(
            ['git', 'config', '--get', 'remote.origin.url'],
            cwd=scan_dirname,
            capture_output=True,
            text=True,
            check=True
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    raw = extract_github_url.stdout.strip()
    if not raw:
        return None

    if raw.startswith(HTTPS_PREFIX) and raw.endswith(DOT_GIT_SUFFIX):
        return raw[LEN_HTTPS_PREFIX:-LEN_DOT_GIT_SUFFIX]

    if raw.startswith(GIT_AT_PREFIX) and raw.endswith(DOT_GIT_SUFFIX):
        normalized = raw[LEN_GIT_AT_PREFIX:-LEN_DOT_GIT_SUFFIX]
        return normalized.replace(':', '/')

    return None

def get_path_mappings_header(
    file_mappings: dict[str, list[dict[str, str]]],
    f: pathlib.Path
) -> typing.Optional[str]:
    mappings: typing.Optional[list[dict[str, str]]] = file_mappings.get(f.as_posix())
    if not mappings:
        return None
    return json.dumps(mappings)

def create_upload_tasks(
    session: aiohttp.ClientSession,
    job_id: str,
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path],
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse
) -> list:

    module_name: typing.Optional[str] = None
    github_url = extract_github_url_from(scan_dirname)
    for f in files:
        if f.name == 'go.mod':
            module_name = extract_module_name_from(scan_dirname / f)
            break

    file_mappings = resolve_file_mappings(scan_dirname, files)

    return [
        upload_single_file(
            session,
            job_id,
            scan_dirname,
            f,
            APPROVED_URL,
            BEARER_TOKEN,
            module_name,
            github_url,
            get_path_mappings_header(file_mappings, f),
            parsed_args
        )
        for f in files
    ]

# pylint: disable=too-many-locals
async def upload(
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path],
    job_id: str,
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse
) -> bool:

    n = len(files)
    percent = '%'
    batches = math.ceil(n / UPLOAD_BATCH_SIZE)
    for i in range(batches):
        start = i * UPLOAD_BATCH_SIZE
        end = (i + 1) * UPLOAD_BATCH_SIZE
        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *create_upload_tasks(
                    session,
                    job_id,
                    scan_dirname,
                    files[start:end],
                    APPROVED_URL,
                    BEARER_TOKEN,
                    parsed_args
                )
            )
        # Multiply before dividing so the percentage doesn't get floored to
        # 0 when batches > 100 (e.g. 10258 files -> 103 batches, where
        # math.floor(100 / 103) == 0 used to make every log line read "0%").
        overall_percentage = min(100, math.floor((i + 1) * 100 / batches))
        # Visibility tweak: surface only round-decile progress at INFO so
        # the human eye gets ~11 anchor lines for any job size; the dense
        # in-between batches go to DEBUG (cyan in the colorized formatter)
        # so they're still scrollable but don't drown the rest of the log.
        if overall_percentage % 10 == 0:
            logging.info('[ step 3 ] uploaded %s%s', overall_percentage, percent)
        else:
            logging.debug('[ step 3 ] uploaded %s%s', overall_percentage, percent)

    return all(results)

def analyze_url(APPROVED_URL: str, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/analyze'

# `analyze` is run-mode-only: it reads parsed_args.with_agent. Typing
# against CliRunArgparse keeps that access mypy-safe and stops it from
# being accidentally called from main_manage in the future.
def analyze(job_id: str, APPROVED_URL: str, APPROVED_BEARER_TOKEN: str, parsed_args: CliRunArgparse, directories: list[str], filenames: list[str]) -> bool:
    params = {'job_id': job_id, 'agent_mode': str(parsed_args.with_agent).lower()}
    url = analyze_url(APPROVED_URL, parsed_args)
    headers = analyze_headers(APPROVED_BEARER_TOKEN)
    body = { 'directories': directories, 'filenames': filenames }
    with requests.post(url, params=params, headers=headers, json=body) as response:
        return response.status_code == http.HTTPStatus.OK

def status_url(APPROVED_URL, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/status'

def check(job_id: str, APPROVED_URL: str, APPROVED_BEARER_TOKEN: str, parsed_args: CliArgparse) -> str:
    params = {'job_id': job_id}
    url = status_url(APPROVED_URL, parsed_args)
    headers = status_headers(APPROVED_BEARER_TOKEN)
    with requests.post(url, params=params, headers=headers) as response:
        if response.status_code == http.HTTPStatus.OK:
            try:
                content = response.json()
                if 'status' in content:
                    status = content['status']
                    if isinstance(status, str):
                        return status
            except json.JSONDecodeError:
                pass

        return 'invalid status response'

def results_url(APPROVED_URL, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/results'

def results_headers(BEARER_TOKEN: str) -> dict:
    return just_authroization_header(BEARER_TOKEN)

def get_results(job_id: str, APPROVED_URL: str, APPROVED_BEARER_TOKEN: str, parsed_args: CliArgparse) -> dict:
    params = {'job_id': job_id}
    url = results_url(APPROVED_URL, parsed_args)
    headers = results_headers(APPROVED_BEARER_TOKEN)
    with requests.post(url, params=params, headers=headers) as response:
        if response.status_code == http.HTTPStatus.OK:
            try:
                return response.json()
            except json.JSONDecodeError:
                pass

    match response.status_code:
        case http.HTTPStatus.INTERNAL_SERVER_ERROR:
            status = http.HTTPStatus.INTERNAL_SERVER_ERROR.phrase
            code = response.status_code
            logging.warning('received %s (%s)', status, code)
            return {}

    logging.warning('received unknown status (%s)', response.status_code)
    return {}

def list_all_job_ids_url(APPROVED_URL: str, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/jobids'

def do_get_all_job_ids(APPROVED_URL: str, BEARER_TOKEN: str, parsed_args: CliArgparse) -> None:
    # Operator-mode entry point: list every job id Redis still knows
    # about so the human can grep/cleanup/cross-ref-against-logs. We
    # reuse the same bearer-token + approved-url plumbing as every other
    # endpoint, so the server-side rate limit and auth apply uniformly.
    url = list_all_job_ids_url(APPROVED_URL, parsed_args)
    headers = just_authroization_header(BEARER_TOKEN)
    try:
        response = requests.get(url, headers=headers)
    except requests.exceptions.ConnectionError:
        logging.warning('[ jobids ] failed to reach %s', url)
        return

    if response.status_code != http.HTTPStatus.OK:
        logging.warning('[ jobids ] http %s from server', response.status_code)
        return

    try:
        payload = response.json()
    except json.JSONDecodeError:
        logging.warning('[ jobids ] invalid json response')
        return

    job_ids = payload.get('job_ids')
    if not isinstance(job_ids, list):
        logging.warning('[ jobids ] missing/invalid job_ids key in: %s', payload)
        return

    if not job_ids:
        logging.info('[ jobids ] no jobs found')
        return

    logging.info('[ jobids ] %d job(s):', len(job_ids))
    # Plain stdout (not via logging) so the output is greppable and
    # pipe-able without timestamps/level decorations contaminating each
    # line (e.g. `python -m cli manage --get-all-job-ids | grep ^abc`).
    for job_id in job_ids:
        print(job_id)

def clear_job_url(APPROVED_URL: str, job_id: str, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/jobs/{job_id}'

def clear_all_url(APPROVED_URL: str, parsed_args: CliArgparse) -> str:
    host = parsed_args.use_external_vps if parsed_args.use_external_vps is not None else LOCALHOST
    port = HTTPS_PORT if parsed_args.use_external_vps is not None else PORT
    return f'{host}:{port}/api/{APPROVED_URL}/jobs'

def do_clear_job_id(
    job_id: str,
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse,
) -> None:
    # Operator-mode entry point: ask the server to evict one job from
    # every runtime store (Redis + SQLite + shared volume + PG logs).
    # This CLI just relays whatever the server reports back.
    url = clear_job_url(APPROVED_URL, job_id, parsed_args)
    headers = just_authroization_header(BEARER_TOKEN)
    try:
        response = requests.delete(url, headers=headers)
    except requests.exceptions.ConnectionError:
        logging.warning('[ clear ] failed to reach %s', url)
        return

    if response.status_code != http.HTTPStatus.OK:
        logging.warning('[ clear ] http %s from server', response.status_code)
        return

    logging.info('[ clear ] job %s cleared (pg logs included)', job_id)

def do_clear_all(
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse,
) -> None:
    # Bulk operator-mode wipe. No client-side confirmation prompt: the
    # opt-in is the flag itself, and the CLI is meant to be scriptable
    # (a TTY-only prompt would silently get skipped in CI anyway).
    url = clear_all_url(APPROVED_URL, parsed_args)
    headers = just_authroization_header(BEARER_TOKEN)
    try:
        response = requests.delete(url, headers=headers)
    except requests.exceptions.ConnectionError:
        logging.warning('[ clear ] failed to reach %s', url)
        return

    if response.status_code != http.HTTPStatus.OK:
        logging.warning('[ clear ] http %s from server', response.status_code)
        return

    try:
        payload = response.json()
        cleared = payload.get('cleared', '?')
    except json.JSONDecodeError:
        cleared = '?'
    logging.info('[ clear ] %s job(s) cleared (pg logs included)', cleared)

def try_connecting_to_server_and_allocate_a_job_id(
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse
) -> typing.Optional[str]:

    connection_established = False
    for _ in range(MAX_ATTEMPTS_CONNECTING_TO_SERVER):
        try:
            job_id = create_job_id(APPROVED_URL, BEARER_TOKEN, parsed_args)
            if job_id is None:
                break
            connection_established = True
            logging.info('[ step 1 ] connection to server established')
            logging.info('[ step 2 ] created job id [ %s....%s ]', job_id[:4], job_id[-5:-1])
            return job_id
        except requests.exceptions.ConnectionError:
            time.sleep(1)

    if not connection_established:
        logging.warning('[ step 1 ] failed connecting to server')

    return None

def upload_files_succeeded(
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path],
    job_id: str,
    APPROVED_URL: str,
    BEARER_TOKEN: str,
    parsed_args: CliArgparse
) -> bool:
    logging.info('[ step 3 ] uploaded started')
    if asyncio.run(upload(scan_dirname, files, job_id, APPROVED_URL, BEARER_TOKEN, parsed_args)):
        logging.info('[ step 3 ] uploaded finished')
        return True

    logging.warning('[ step 3 ] uploaded failed, aborting')
    return False

# pylint: disable=too-many-nested-blocks
def remove_loops(sarif: dict) -> dict:
    for sarif_run in sarif.get('runs', []):
        for result in sarif_run.get('results', []):
            for codeFlow in result.get('codeFlows', []):
                for threadFlow in codeFlow.get('threadFlows', []):
                    locations = threadFlow.get('locations', [])
                    normalized: list = []
                    for loc in locations:
                        if not normalized or json.dumps(loc) != json.dumps(normalized[-1]):
                            normalized.append(loc)
                    threadFlow['locations'] = normalized
    return sarif

# Dispatcher base. Picks the concrete impl based on the runtime type
# of parsed_args (registrations below). Because CliArgparse.parse()
# can only return a CliRunArgparse or a CliManageArgparse — and both
# are registered — the base body is unreachable at runtime; we still
# define it (and raise) to (a) give callers a single stable entry
# point and (b) surface any future "added a subcommand but forgot to
# register" mistake loudly instead of silently no-op'ing.
# pylint: disable=unused-argument
@functools.singledispatch
def main(parsed_args: CliArgparse, APPROVED_URL: str, BEARER_TOKEN: str) -> None:
    raise NotImplementedError(f'no main impl for {type(parsed_args).__name__}')


@main.register
def run(parsed_args: CliRunArgparse, APPROVED_URL: str, BEARER_TOKEN: str) -> None:

    # Scan-mode entry point. Allocates a job id, collects + uploads
    # files, kicks off analysis, polls for completion, then either
    # surfaces the kb path (agent mode) or writes/prints sarif. Typed
    # against CliRunArgparse so parsed_args.scan_dirname is statically
    # known to be set (not Optional) and parsed_args.with_agent /
    # .save_sarif_to are reachable without isinstance narrowing.
    if job_id := try_connecting_to_server_and_allocate_a_job_id(APPROVED_URL, BEARER_TOKEN, parsed_args):
        if files := collect_relevant_files(parsed_args.scan_dirname):
            directories, filenames = collect_directories_and_filenames(files)
            if upload_files_succeeded(
                parsed_args.scan_dirname,
                files,
                job_id,
                APPROVED_URL,
                BEARER_TOKEN,
                parsed_args
            ):
                if analyze(job_id, APPROVED_URL, BEARER_TOKEN, parsed_args, directories, filenames):
                    for _ in range(MAX_NUM_CHECKS):
                        what_should_happen_next = check(job_id, APPROVED_URL, BEARER_TOKEN, parsed_args)
                        if what_should_happen_next != 'Finished':
                            logging.info('[ step 4 ] now %s', what_should_happen_next)
                            time.sleep(NUM_SECONDS_BETEEN_STEP_CHECK)
                        else:
                            logging.info('[ step 5 ] finished 🙂')
                            if parsed_args.with_agent:
                                results = get_results(job_id, APPROVED_URL, BEARER_TOKEN, parsed_args)
                                kb_location = results.get('kb_location')
                                if isinstance(kb_location, str):
                                    logging.info('[ step 6 ] kb filename: %s', kb_location)
                                    logging.info('[ step 6 ] copy this filename for agent mode continuation')
                                else:
                                    logging.warning('[ step 6 ] missing kb filename in results: %s', results)
                                break

                            results = get_results(job_id, APPROVED_URL, BEARER_TOKEN, parsed_args)
                            if output := parsed_args.save_sarif_to:
                                logging.info('[ step 6 ] saved sarif to: %s', output)
                                with open(output, 'w', encoding='utf-8') as fl:
                                    json.dump(results, fl)
                            else:
                                logging.info('[ step 6 ] received sarif:\n%s', results)
                            break


@main.register
def launch_local_app(
    parsed_args: CliLaunchLocalAppArgparse,
    APPROVED_URL: str,
    BEARER_TOKEN: str,
) -> None:

    # Agent-driven launcher entry point: hand control to the dedicated
    # launcher module. APPROVED_URL / APPROVED_BEARER_TOKEN are unused
    # here (the launcher only ever talks to localhost on the target
    # app's port + the OpenAI API), but the dispatcher contract still
    # requires them so this arm stays in shape with `run`/`manage`.
    del APPROVED_URL, BEARER_TOKEN
    exit_code = local_app_launcher.launch(parsed_args)
    if exit_code != 0:
        raise SystemExit(exit_code)


@main.register
def manage(parsed_args: CliManageArgparse, APPROVED_URL: str, BEARER_TOKEN: str) -> None:

    # Operator-mode entry point. Dispatches on whichever of the three
    # mutually-exclusive flags the user picked; argparse already
    # enforced "exactly one of {get_all_job_ids, clear_job_id,
    # clear_all}" is set, so the dispatch chain is exhaustive.
    if parsed_args.get_all_job_ids:
        do_get_all_job_ids(APPROVED_URL, BEARER_TOKEN, parsed_args)
        return
    if parsed_args.clear_job_id is not None:
        do_clear_job_id(parsed_args.clear_job_id, APPROVED_URL, BEARER_TOKEN, parsed_args)
        return
    if parsed_args.clear_all:
        do_clear_all(APPROVED_URL, BEARER_TOKEN, parsed_args)
        return


def main_entry() -> None:
    parsed = CliArgparse.parse()
    logging.info('[ step 0 ] required args ok 😊')
    # The launch-local-app subcommand only ever drives a local
    # subprocess + OpenAI; it never reaches an approved url or a
    # bearer token, so we bypass the env-var gate that the other two
    # subcommands need. Passing empty strings keeps the dispatcher
    # signature uniform without leaking irrelevant config requirements
    # onto users who only want to launch a target app.
    if isinstance(parsed, CliLaunchLocalAppArgparse):
        main(parsed, '', '')
    elif APPROVED_URL_0 := os.getenv('APPROVED_URL_0', None):
        if APPROVED_BEARER_TOKEN_0 := os.getenv('APPROVED_BEARER_TOKEN_0', None):
            main(parsed, APPROVED_URL_0, APPROVED_BEARER_TOKEN_0)


if __name__ == "__main__":
    main_entry()
