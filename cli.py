from __future__ import annotations

import os
import sys
import http
import math
import json
import time
import typing
import pathlib
import asyncio
import logging
import aiofiles
import aiohttp
import requests
import argparse
import dataclasses

ARGPARSE_PROG_DESC: typing.Final[str] = """

simple dev script to send repo for dhscanner inspection
"""

ARGPARSE_SCAN_DIRNAME_HELP: typing.Final[str] = """
relative / absolute path of the dir you want to scan
"""

ARGPARSE_IGNORE_TESTING_CODE_HELP: typing.Final[str] = """
ignore testing code
"""

ARGPARSE_SHOW_PARSE_STATUS_FOR_FILE_HELP: typing.Final[str] = """
print parse status for file
"""

LOCALHOST: typing.Final[str] = 'http://localhost'
PORT: typing.Final[int] = 8000

SUFFIXES: typing.Final[set[str]] = {
    'py', 'ts', 'js', 'php', 'rb', 'java', 'cs', 'go'   
}

MAX_ATTEMPTS_CONNECTING_TO_SERVER = 10
UPLOAD_BATCH_SIZE = 100
MAX_NUM_CHECKS = 100
NUM_SECONDS_BETEEN_STEP_CHECK = 5

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s]: %(message)s",
    datefmt="%d/%m/%Y ( %H:%M:%S )",
    stream=sys.stdout
)

def existing_non_empty_dirname(name: str) -> pathlib.Path:

    candidate = pathlib.Path(name)

    if not candidate.is_dir():
        message = f'directory {name} does not exist'
        raise argparse.ArgumentTypeError(message)

    if not any(candidate.iterdir()):
        message = f'no files found in directory: {name}'
        raise argparse.ArgumentTypeError(message)

    return candidate

def proper_bool_value(name: str) -> bool:

    if name not in ['true', 'false']:
        message = 'please specify true | false for including testing code'
        raise argparse.ArgumentTypeError(message)

    return name == 'true'

@dataclasses.dataclass(frozen=True, kw_only=True)
class Argparse:

    scan_dirname: pathlib.Path
    ignore_testing_code: bool

    @staticmethod
    def run() -> typing.Optional[Argparse]:

        parser = argparse.ArgumentParser(
            description=ARGPARSE_PROG_DESC
        )

        parser.add_argument(
            '--scan_dirname',
            required=True,
            type=existing_non_empty_dirname,
            metavar="dir/you/want/to/scan",
            help=ARGPARSE_SCAN_DIRNAME_HELP
        )

        parser.add_argument(
            '--ignore_testing_code',
            required=True,
            type=proper_bool_value,
            metavar='true | false',
            help=ARGPARSE_IGNORE_TESTING_CODE_HELP
        )

        parsed_args = parser.parse_args()

        logging.info('[ step 0 ] required args ok 😊')

        return Argparse(
            scan_dirname=parsed_args.scan_dirname,
            ignore_testing_code=parsed_args.ignore_testing_code
        )

def relevant(filename: pathlib.Path) -> bool:
    if filename.suffix.lstrip('.') not in SUFFIXES:
        return False

    resolved = filename.resolve()
    parts = resolved.parts
    name = str(resolved)
    if 'test' in parts:
        return False

    if '.test.' in name:
        return False

    if name.endswith('.d.ts'):
        return False

    return True

def collect_relevant_files(scan_dirname: pathlib.Path) -> list[pathlib.Path]:

    filenames = []
    for root, _, files in os.walk(scan_dirname):
        for filename in files:
            abspath_filename = pathlib.Path(root) / filename
            if relevant(abspath_filename):
                filenames.append(abspath_filename.relative_to(scan_dirname))

    if filenames:
        logging.info('[ step 2 ] collected %s files', len(filenames))
    else:
        logging.warning('[ step 2 ] no files were collected')

    return filenames

def create_job_id(APPROVED_URL: str, BEARER_TOKEN: str) -> typing.Optional[str]:
    headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
    url = f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/getjobid'
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

def upload_url(APPROVED_URL: str) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/upload'

def upload_headers(BEARER_TOKEN: str, filename: str) -> dict:
    return {
        'Authorization': f'Bearer {BEARER_TOKEN}',
        'X-Path': filename,
        'Content-Type': 'application/octet-stream'
    }

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

async def actual_upload(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    params: dict,
    scan_dirname: pathlib.Path,
    f: pathlib.Path
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
    BEARER_TOKEN: str
) -> bool:

    params = {'job_id': job_id}
    url = upload_url(APPROVED_URL)
    headers = upload_headers(BEARER_TOKEN, f.as_posix())
    return await actual_upload(session, url, headers, params, scan_dirname, f)

def create_upload_tasks(
    session: aiohttp.ClientSession,
    job_id: int,
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path],
    APPROVED_URL: str,
    BEARER_TOKEN: str
) -> list:
    return [
        upload_single_file(
            session,
            job_id,
            scan_dirname,
            f,
            APPROVED_URL,
            BEARER_TOKEN,
        )
        for f in files
    ]

async def upload(
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path],
    job_id: str,
    APPROVED_URL: str,
    BEARER_TOKEN: str
) -> bool:

    n = len(files)
    percent = '%'
    batches = math.ceil(n / UPLOAD_BATCH_SIZE)
    percentage_for_1_batch = math.floor(100 / batches)
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
                    BEARER_TOKEN
                )
            )
        overall_percentage = min(100, (i + 1) * percentage_for_1_batch)
        logging.info('[ step 3 ] uploaded %s%s', overall_percentage, percent)

    return all(results)

def analyze_url(APPROVED_URL) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/analyze'

def analyze(job_id: str) -> bool:
    params = {'job_id': job_id}
    url = analyze_url(APPROVED_URL_0)
    headers = analyze_headers(APPROVED_BEARER_TOKEN_0)
    with requests.post(url, params=params, headers=headers) as response:
        return response.status_code == http.HTTPStatus.OK

def status_url(APPROVED_URL) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/status'

def check(job_id: str) -> str:
    params = {'job_id': job_id}
    url = status_url(APPROVED_URL_0)
    headers = status_headers(APPROVED_BEARER_TOKEN_0)
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

def results_url(APPROVED_URL) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/results'

def results_headers(BEARER_TOKEN: str) -> dict:
    return just_authroization_header(BEARER_TOKEN)

def get_results(job_id: str) -> dict:
    params = {'job_id': job_id}
    url = results_url(APPROVED_URL_0)
    headers = results_headers(APPROVED_BEARER_TOKEN_0)
    with requests.post(url, params=params, headers=headers) as response:
        if response.status_code == http.HTTPStatus.OK:
            try:
                return response.json()
            except json.JSONDecodeError:
                pass

    logging.warning('received %s', response.status_code)
    return {}

def try_connecting_to_server_and_allocate_a_job_id(
    APPROVED_URL: str,
    BEARER_TOKEN: str
) -> typing.Optional[str]:

    connection_established = False
    for _ in range(MAX_ATTEMPTS_CONNECTING_TO_SERVER):
        try:
            job_id = create_job_id(APPROVED_URL, BEARER_TOKEN)
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
    BEARER_TOKEN: str
) -> bool:
    logging.info('[ step 3 ] uploaded started')
    if asyncio.run(upload(scan_dirname, files, job_id, APPROVED_URL, BEARER_TOKEN)):
        logging.info('[ step 3 ] uploaded finished')
        return True

    logging.warning('[ step 3 ] uploaded failed, aborting')
    return False

def main(parsed_args: Argparse, APPROVED_URL: str, BEARER_TOKEN: str) -> None:

    if job_id := try_connecting_to_server_and_allocate_a_job_id(APPROVED_URL, BEARER_TOKEN):
        if files := collect_relevant_files(parsed_args.scan_dirname):
            if upload_files_succeeded(
                parsed_args.scan_dirname,
                files,
                job_id,
                APPROVED_URL,
                BEARER_TOKEN
            ):
                if analyze(job_id):
                    for _ in range(MAX_NUM_CHECKS):
                        what_should_happen_next = check(job_id)
                        if what_should_happen_next != 'Finished':
                            logging.info('[ step 4 ] now %s', what_should_happen_next)
                            time.sleep(NUM_SECONDS_BETEEN_STEP_CHECK)
                        else:
                            results = get_results(job_id)
                            logging.info('[ step 5 ] Finished 🙂')
                            logging.info('[ step 6 ] Received Sarif:\n%s', results)
                            break

if __name__ == "__main__":
    if args := Argparse.run():
        if APPROVED_URL_0 := os.getenv('APPROVED_URL_0', None):
            if APPROVED_BEARER_TOKEN_0 := os.getenv('APPROVED_BEARER_TOKEN_0', None):
                main(args, APPROVED_URL_0, APPROVED_BEARER_TOKEN_0)
