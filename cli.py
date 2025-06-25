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
        message = f'please specify true | false for including testing code'
        raise argparse.ArgumentTypeError(message)

    return True if name == 'true' else False

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

        args = parser.parse_args()

        logging.info('[ step 0 ] required args ok 😊')

        return Argparse(
            scan_dirname=args.scan_dirname,
            ignore_testing_code=args.ignore_testing_code
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

    return True

def collect_relevant_files(scan_dirname: pathlib.Path) -> list[pathlib.Path]:

    filenames = []
    for root, _, files in os.walk(scan_dirname):
        for filename in files:
            abspath_filename = pathlib.Path(root) / filename
            if relevant(abspath_filename):
                filenames.append(abspath_filename)

    return filenames

def create_job_id(APPROVED_URL: str, BEARER_TOKEN: str) -> typing.Optional[str]:
    headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
    url = f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/getjobid'
    response = requests.get(url, headers=headers)
    if response.status_code != http.HTTPStatus.OK:
        logging.error(f'failed to create job id: http status code {response.status_code}')
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
        logging.error(f'upload failed for {filename} http status: {status}')
        return False

    try:
        result = await response.json()
        if 'status' in result:
            if result['status'] == 'ok':
                return True
    except json.JSONDecodeError:
        logging.error(f'Invalid upload response for {filename}')
    
    return False

async def actual_upload(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    params: dict,
    f: pathlib.Path
) -> bool:
    
    try:
        async with aiofiles.open(f, 'rb') as content:
            async with session.post(url, params=params, headers=headers, data=content) as response:
                return await check_response(response, f.name)
    except FileNotFoundError:
        return None

async def upload_single_file(
    session: aiohttp.ClientSession,
    job_id: str,
    f: pathlib.Path,
    APPROVED_URL: str,
    BEARER_TOKEN: str
) -> bool:

    params = {'job_id': job_id}
    url = upload_url(APPROVED_URL)
    headers = upload_headers(BEARER_TOKEN, str(f.resolve()))
    return await actual_upload(session, url, headers, params, f)

def create_upload_tasks(
    session: aiohttp.ClientSession,
    job_id: int,
    files: list[pathlib.Path],
    APPROVED_URL: str,
    BEARER_TOKEN: str
) -> list:
    return [
        upload_single_file(
            session,
            job_id,
            f,
            APPROVED_URL,
            BEARER_TOKEN,
        )
        for f in files
    ]

async def upload(
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
                    files[start:end],
                    APPROVED_URL,
                    BEARER_TOKEN
                )
            )
        overall_percentage = min(100, (i + 1) * percentage_for_1_batch)
        logging.info(f'[ step 3 ] uploaded {overall_percentage}{percent}')

    return all(results)

def analyze_url(APPROVED_URL) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/analyze'

def analyze(job_id: str) -> bool:
    params = {'job_id': job_id}
    url = analyze_url(APPROVED_URL)
    headers = analyze_headers(BEARER_TOKEN)
    with requests.post(url, params=params, headers=headers) as response:
        return response.status_code == http.HTTPStatus.OK

def status_url(APPROVED_URL) -> str:
    return f'{LOCALHOST}:{PORT}/api/{APPROVED_URL}/status'

def check(job_id: str) -> str:
    params = {'job_id': job_id}
    url = status_url(APPROVED_URL)
    headers = status_headers(BEARER_TOKEN)
    with requests.post(url, params=params, headers=headers) as response:
        if response.status_code == http.HTTPStatus.OK:
            return 'MOMO'

def main(args: Argparse, APPROVED_URL: str, BEARER_TOKEN: str) -> None:

    for _ in range(MAX_ATTEMPTS_CONNECTING_TO_SERVER):
        try:
            job_id = create_job_id(APPROVED_URL, BEARER_TOKEN)
            if job_id is None: return
            logging.info(f'[ step 1 ] created job id {job_id}')
            break
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            pass

    files = collect_relevant_files(args.scan_dirname)
    if len(files) == 0: return
    logging.info(f'[ step 2 ] collected {len(files)} files')

    logging.info(f'[ step 3 ] uploaded started')
    status = asyncio.run(upload(files, job_id, APPROVED_URL, BEARER_TOKEN))
    if status is False: return
    logging.info(f'[ step 3 ] uploaded finished')

    if analyze(job_id):
        for _ in range(MAX_NUM_CHECKS):
            step = check(job_id)
            logging.info(f'[ step {step} ] finished')
            time.sleep(NUM_SECONDS_BETEEN_STEP_CHECK)

if __name__ == "__main__":
    if args := Argparse.run():
        if APPROVED_URL := os.getenv('APPROVED_URL_0', None):
            if BEARER_TOKEN := os.getenv('APPROVED_BEARER_TOKEN_0', None):
                main(args, APPROVED_URL, BEARER_TOKEN)
