import asyncio
import typing

import aiofiles
import aiohttp
import requests
import collections

from language import Language
from coordinator import Coordinator
from redis_coordinator import RedisCoordinator

import models
import storage

AST_BUILDER_URL = {
    Language.JS: 'http://frontjs:3000/to/esprima/js/ast',
    Language.TS: 'http://frontts:3000/to/native/ts/ast',
    Language.TSX: 'http://frontts:3000/to/native/ts/ast',
    Language.PHP: 'http://frontphp:5000/to/php/ast',
    Language.PY: 'http://frontpy:5000/to/native/py/ast',
    Language.RB: 'http://frontrb:3000/to/native/cruby/ast',
    Language.CS: 'http://frontcs:8080/to/native/cs/ast',
    Language.GO: 'http://frontgo:8080/to/native/go/ast',
    Language.BLADE_PHP: 'http://frontphp:5000/to/php/code'
}

CSRF_TOKEN = 'http://frontphp:5000/csrf_token'

# TODO: adjust other reasons for exclusion
# the reasons might depend on the language
# (like the third party directory name: node_module for javascript,
# site-packages for python or vendor/bundle for ruby etc.)
# pylint: disable=unused-argument
def scan_worthy(f: models.FileMetadata) -> bool:

    if '/test/' in f.original_filename:
        return False

    if '.test.' in f.original_filename:
        return False

    return True

async def parse(
    session: aiohttp.ClientSession,
    code: dict[str, typing.Tuple[str, bytes]],
    f: models.FileMetadata
) -> typing.Optional[str]:

    async with session.post(AST_BUILDER_URL[f.language], data=code) as response:
            return await response.text()

async def read_source_file(
    filename: str,
    original_filename: str
) -> dict[str, typing.Tuple[str, bytes]]:

    async with aiofiles.open(filename, 'rb') as f:
        code = await f.read()

    return { 'source': (original_filename, code) }

async def run_single_file(
    session: aiohttp.ClientSession,
    job_id: str,
    f: models.FileMetadata
) -> None:
    code = await read_source_file(f.file_unique_id)
    content = await parse(session, code, f)
    await storage.store_ast(content, f, job_id)

async def run(job_id: str) -> None:

    files = storage.load_files_metadata_from_db(job_id)
    async with aiohttp.ClientSession() as session:
        tasks = [run_single_file(session, job_id, f) for f in files if scan_worthy(f)]
        await asyncio.gather(*tasks)

async def worker_loop_internal(job_ids: list[str]) -> None:
    tasks = [run(job_id) for job_id in job_ids]
    await asyncio.gather(*tasks)

async def worker_loop(the_coordinator: Coordinator) -> None:
    while True:
        await worker_loop_internal(the_coordinator.get_jobs_waiting_for_step_0_native_parsing())
        await asyncio.sleep(1)

def check_in() -> None:
     asyncio.run(worker_loop(RedisCoordinator()))