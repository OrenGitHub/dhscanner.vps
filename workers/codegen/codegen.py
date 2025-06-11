import json
import typing
import aiohttp
import asyncio
import requests
import dataclasses

import storage

from workers.interface import AbstractWorker

TO_CODEGEN_URL = 'http://codegen:3000/codegen'

@dataclasses.dataclass(frozen=True)
class Codegen(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        files = storage.load_files_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            tasks = [self.run_single_file(session, job_id, f) for f in files]
            await asyncio.gather(*tasks)


def codegen(dhscanner_asts):

    callables = []
    for ast in dhscanner_asts:
        response = requests.post(TO_CODEGEN_URL, json=ast)
        more_callables = json.loads(response.text)['actualCallables']
        callables.extend(more_callables)

    return callables
