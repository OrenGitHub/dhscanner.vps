import http
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

TO_QUERY_ENGINE_URL = 'http://queryengine:5000/check'

@dataclasses.dataclass(frozen=True)
class Queryengine(AbstractWorker):

    # pylint: disable=too-many-locals
    @typing.override
    async def run(self, job_id: str) -> None:
        emessage = 'none'
        start = time.monotonic()
        files = self.the_storage_guy.load_facts_metadata_from_db(job_id)
        tasks = [self.read_facts(facts) for facts in files]
        contents = await asyncio.gather(*tasks)
        flatten = [fact for facts in contents for fact in facts]
        kb = '\n'.join(sorted(set(flatten)))
        form = aiohttp.FormData()
        form.add_field(name='kb', value=kb, content_type='text/plain')
        form.add_field(name='queries', value=kb, content_type='text/plain')
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(TO_QUERY_ENGINE_URL, data=form) as response:
                    if response.status == http.HTTPStatus.OK:
                        content = await response.text()
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

            except aiohttp.ClientError as e:
                emessage = str(e)

            end = time.monotonic()
            delta = end - start
            part_1 = f'response status: {response.status}'
            part_2 = f'exception(s): {emessage}'
            await self.the_logger_dude.info(
                LogMessage(
                    file_unique_id=f'queries_{job_id}',
                    job_id=job_id,
                    context=Context.QUERYENGINE_FAILED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta),
                    more_details=f'{part_1}, {part_2}'
                )
            )

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForResultsGeneration
            )

    async def read_facts(self, f: FactsMetadata) -> list[str]:
        async with aiofiles.open(f.facts_unique_id, 'rt', encoding='utf-8') as fl:
            lines = await fl.readlines()
            result = [line.strip() for line in lines]
        await self.the_storage_guy.delete_knowledge_base_facts(f)
        return result
