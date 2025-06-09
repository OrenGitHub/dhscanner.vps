import asyncio
import aiohttp

import storage

from coordinator import Coordinator
from redis_coordinator import RedisCoordinator

TO_KBGEN_URL = 'http://kbgen:3000/kbgen'

async def run(job_id: str) -> None:

    files = storage.load_files_metadata_from_db(job_id)
    async with aiohttp.ClientSession() as session:
        tasks = [run_single_file(session, job_id, f) for f in files]
        await asyncio.gather(*tasks)
