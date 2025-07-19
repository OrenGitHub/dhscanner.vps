import http
import json
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from coordinator.interface import Status
from logger.models import Context, LogMessage
from storage.models import CallablesMetadata
from workers.interface import AbstractWorker

TO_KBGEN_URL = 'http://kbgen:3000/kbgen'

@dataclasses.dataclass(frozen=True)
class Kbgen(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        cs = self.the_storage_guy.load_callables_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as s:
            tasks = [self.kbgen_ith_callable(s, c, i) for c in cs for i in range(c.num_callables)]
            await asyncio.gather(*tasks)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForQueryengine
            )

    async def kbgen_ith_callable(
        self,
        session: aiohttp.ClientSession,
        c: CallablesMetadata,
        i: int
    ) -> None:

        if _callable := await self.read_ith_callablle_file(c, i):
            if content := await self.kbgen(session, _callable, c, i):
                await self.the_storage_guy.save_knowledge_base_facts(content, c, i)
        await self.the_storage_guy.delete_ith_callable(c, i)

    async def kbgen(
        self,
        session: aiohttp.ClientSession,
        _callable: dict[str, typing.Tuple[str, bytes]],
        c: CallablesMetadata,
        i: int
    ) -> typing.Optional[str]:
        emessage = 'none'
        start = time.monotonic()
        try:
            async with session.post(TO_KBGEN_URL, json=_callable) as response:
                if response.status == http.HTTPStatus.OK:
                    facts = await response.json()
                    end = time.monotonic()
                    delta = end - start
                    if 'content' in facts:
                        await self.the_logger_dude.info(
                            LogMessage(
                                file_unique_id=c.callable_unique_id,
                                job_id=c.job_id,
                                context=Context.KBGEN_SUCCEEDED,
                                original_filename=c.original_filename,
                                language=c.language,
                                duration=timedelta(seconds=delta),
                                more_details=f'callable({i+1})'
                            )
                        )
                        return facts['content']

        except aiohttp.ClientError as e:
            emessage = str(e)

        except json.JSONDecodeError as e:
            emessage = str(e)

        end = time.monotonic()
        delta = end - start
        part_1 = f'callable({i+1})'
        part_2 = f'response status: {response.status}'
        part_3 = f'exception(s): {emessage}'
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=c.callable_unique_id,
                job_id=c.job_id,
                context=Context.KBGEN_FAILED,
                original_filename=c.original_filename,
                language=c.language,
                duration=timedelta(seconds=delta),
                more_details=f'{part_1}, {part_2}, {part_3}'
            )
        )
        return None

    async def read_ith_callablle_file(self, c: CallablesMetadata, i: int) -> typing.Optional[dict]:
        return await self.the_storage_guy.load_ith_callable(c, i)
