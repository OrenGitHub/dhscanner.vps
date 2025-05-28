import typing
import aiohttp
import asyncio
import aiofiles

import models
import storage

from language import Language
from coordinator import Coordinator
from redis_coordinator import RedisCoordinator

DHSCANNER_AST_BUILDER_URL = {
    Language.JS: 'http://parsers:3000/from/js/to/dhscanner/ast',
    Language.TS: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.TSX: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.PHP: 'http://parsers:3000/from/php/to/dhscanner/ast',
    Language.PY: 'http://parsers:3000/from/py/to/dhscanner/ast',
    Language.RB: 'http://parsers:3000/from/rb/to/dhscanner/ast',
    Language.CS: 'http://parsers:3000/from/cs/to/dhscanner/ast',
    Language.GO: 'http://parsers:3000/from/go/to/dhscanner/ast',
}

async def parse(
    session: aiohttp.ClientSession,
    code: dict[str, typing.Tuple[str, bytes]],
    f: models.FileMetadata
) -> typing.Optional[str]:

    async with session.post(DHSCANNER_AST_BUILDER_URL[f.language], data=code) as response:
            return await response.text()

async def read_ast_file(
    filename: str,
    original_filename: str
) -> dict[str, typing.Tuple[str, bytes]]:

    async with aiofiles.open(filename, 'rb') as f:
        ast = await f.read()

    return { 'source': (original_filename, ast) }

async def run_single_ast(
    session: aiohttp.ClientSession,
    job_id: str,
    f: models.FileMetadata
) -> None:
    ast = await read_ast_file(f.file_unique_id)
    dhscanner_ast = await parse(session, ast, f)
    await storage.store_dhscanner_ast(dhscanner_ast, f, job_id)

async def run(job_id: str) -> None:

    asts = storage.load_asts_metadata_from_db(job_id)
    async with aiohttp.ClientSession() as session:
        tasks = [run_single_ast(session, job_id, f) for f in asts]
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