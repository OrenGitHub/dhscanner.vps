import asyncio
import json
import aiohttp
import requests

from coordinator import Coordinator
from redis_coordinator import RedisCoordinator
import storage


TO_CODEGEN_URL = 'http://codegen:3000/codegen'

def codegen(dhscanner_asts):

    callables = []
    for ast in dhscanner_asts:
        response = requests.post(TO_CODEGEN_URL, json=ast)
        more_callables = json.loads(response.text)['actualCallables']
        # logging.info(more_callables)
        callables.extend(more_callables)

    return callables

async def run(job_id: str) -> None:

    files = storage.load_files_metadata_from_db(job_id)
    async with aiohttp.ClientSession() as session:
        tasks = [run_single_file(session, job_id, f) for f in files]
        await asyncio.gather(*tasks)

async def worker_loop_internal(job_ids: list[str]) -> None:
    tasks = [run(job_id) for job_id in job_ids]
    await asyncio.gather(*tasks)

async def worker_loop(the_coordinator: Coordinator) -> None:
    while True:
        await worker_loop_internal(the_coordinator.get_jobs_waiting_for_step_2_code_generation())
        await asyncio.sleep(1)

def check_in() -> None:
     asyncio.run(worker_loop(RedisCoordinator()))
