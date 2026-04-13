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
TO_QUERY_ENGINE_URL_UPLOAD_ONLY = 'http://queryengine:3000/uploadkb'

@dataclasses.dataclass(frozen=True)
class Queryengine(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        files = self.the_storage_guy.load_facts_metadata_from_db(job_id)
        tasks = [self.read_facts_json(facts) for facts in files]
        contents = await asyncio.gather(*tasks)
        all_facts: list[dict] = []
        for fact_list in contents:
            all_facts.extend(fact_list)

        if self.the_coordinator.get_agent_mode(job_id):
            await self.run_with_agent_mode(job_id, all_facts)
        else:
            await self.run_without_agent(job_id, all_facts)

    async def run_with_agent_mode(self, job_id: str, all_facts: list[dict]) -> None:
        emessage = 'no exception'
        start = time.monotonic()

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(TO_QUERY_ENGINE_URL_UPLOAD_ONLY, json=all_facts) as response:
                    if response.status == http.HTTPStatus.OK:
                        result_json: dict[str, str] = await response.json()
                        if kb_location := result_json.get('kb_location', None):
                            self.the_coordinator.set_kb_location(job_id, kb_location)
                            end = time.monotonic()
                            delta = end - start
                            await self.the_logger_dude.info(
                                LogMessage(
                                    file_unique_id=f'queries_{job_id}',
                                    job_id=job_id,
                                    context=Context.KBGEN_UPLOADED_FOR_AGENT,
                                    original_filename='*',
                                    language=Language.ALL,
                                    duration=timedelta(seconds=delta)
                                )
                            )
                            return
                        else:
                            emessage = 'invalid json response without kb location'

            except aiohttp.ClientError as e:
                emessage = str(e)

            end = time.monotonic()
            delta = end - start
            await self.the_logger_dude.info(
                LogMessage(
                    file_unique_id=f'queries_{job_id}',
                    job_id=job_id,
                    context=Context.KBGEN_UPLOAD_FOR_AGENT_FAILED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta),
                    more_details=f'exception(s): {emessage}'
                )
            )

    # pylint: disable=too-many-locals
    async def run_without_agent(self, job_id: str, all_facts: list[dict]) -> None:
        emessage = 'no exception'
        start = time.monotonic()

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(TO_QUERY_ENGINE_URL, json=all_facts) as response:
                    if response.status == http.HTTPStatus.OK:
                        result_json = await response.json()
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
            await self.the_logger_dude.info(
                LogMessage(
                    file_unique_id=f'queries_{job_id}',
                    job_id=job_id,
                    context=Context.QUERYENGINE_FAILED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta),
                    more_details=f'exception(s): {emessage}'
                )
            )

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            if self.the_storage_guy.load_results_metadata_from_db(job_id) is None:
                await self.the_logger_dude.info(
                    LogMessage(
                        file_unique_id=f'queries_{job_id}',
                        job_id=job_id,
                        context=Context.QUERYENGINE_FAILED,
                        original_filename='*',
                        language=Language.ALL,
                        duration=timedelta(seconds=0),
                        more_details='results metadata missing'
                    )
                )
                self.the_coordinator.set_status(
                    job_id,
                    Status.Finished
                )
                continue

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
