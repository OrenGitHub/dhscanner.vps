import http
import json
import time
import typing
import aiohttp
import asyncio
import aiofiles
import dataclasses

from datetime import timedelta

from common.language import Language
from coordinator.interface import Status
from storage.models import FactsMetadata
from logger.models import Context, LogMessage
from workers.interface import AbstractWorker

TO_QUERY_ENGINE_URL = 'http://queryengine:3000/querycheck'

@dataclasses.dataclass(frozen=True)
class Queryengine(AbstractWorker):

    # pylint: disable=too-many-locals
    @typing.override
    async def run(self, job_id: str) -> None:
        emessage = 'no exception'
        start = time.monotonic()
        files = self.the_storage_guy.load_facts_metadata_from_db(job_id)
        tasks = [self.read_facts_json(facts) for facts in files]
        contents = await asyncio.gather(*tasks)
        # Concatenate all JSON fact lists into one big list
        all_facts = []
        for fact_list in contents:
            all_facts.extend(fact_list)

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(TO_QUERY_ENGINE_URL, json=all_facts) as response:
                    if response.status == http.HTTPStatus.OK:
                        result_json = await response.json()
                        # Extract stdout from the JSON response
                        content = result_json.get('stdout', '')
                        await self.the_storage_guy.save_results(content, job_id)
                        end = time.monotonic()
                        delta = end - start
                        await self.the_logger_dude.info(
                            LogMessage(
                                file_unique_id=f'queries_{job_id}',
                                job_id=job_id,
                                context=Context.QUERYENGINE_SUCCEEDED,
                                original_filename='*',
                                language=Language.ALL,
                                duration=timedelta(seconds=delta)
                            )
                        )
                        return
                    if response.status == http.HTTPStatus.GATEWAY_TIMEOUT:
                        await self.the_storage_guy.save_results('TimeoutExpired', job_id)
                        end = time.monotonic()
                        delta = end - start
                        await self.the_logger_dude.info(
                            LogMessage(
                                file_unique_id=f'queries_{job_id}',
                                job_id=job_id,
                                context=Context.QUERYENGINE_SUCCEEDED,
                                original_filename='*',
                                language=Language.ALL,
                                duration=timedelta(seconds=delta),
                                more_details='query engine timeout'
                            )
                        )
                        return

            except aiohttp.ClientError as e:
                emessage = str(e)

            end = time.monotonic()
            delta = end - start
            part_1 = f'exception(s): {emessage}'
            await self.the_logger_dude.info(
                LogMessage(
                    file_unique_id=f'queries_{job_id}',
                    job_id=job_id,
                    context=Context.QUERYENGINE_FAILED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta),
                    more_details=f'{part_1}'
                )
            )

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForResultsGeneration
            )

    async def read_facts_json(self, f: FactsMetadata) -> list[dict]:
        async with aiofiles.open(f.facts_unique_id, 'rt', encoding='utf-8') as fl:
            content = await fl.read()
            result = json.loads(content)
        await self.the_storage_guy.delete_knowledge_base_facts(f)
        return result
