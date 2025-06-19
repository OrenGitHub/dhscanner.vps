import json
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from logger.models import Context, LogMessage
from storage.models import CallablesMetadata, FileMetadata
from workers.interface import AbstractWorker

TO_KBGEN_URL = 'http://kbgen:3000/kbgen'

@dataclasses.dataclass(frozen=True)
class Kbgen(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        callables = self.the_storage_guy.load_callables_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as s:
            tasks = [self.kbgen_ith_callable(s, c, i) for c, i in enumerate(callables)]
            await asyncio.gather(*tasks)

    async def kbgen_ith_callable(
        self,
        session: aiohttp.ClientSession,
        c: CallablesMetadata,
        i: int
    ) -> None:
        if _callable := await self.read_ith_callablle_file(c, i):
            if content := await self.kbgen(session, _callable, c):
                await self.the_storage_guy.save_knowledge_base_facts(content, c, i)
                await self.the_storage_guy.delete_callables(c, i)

    async def kbgen(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        c: CallablesMetadata
    ) -> typing.Optional[dict]:
        start = time.monotonic()
        try:
            async with session.post(TO_KBGEN_URL, data=code) as response:
                if response.status == 200:
                    dhscanner_ast = await response.text()
                    end = time.monotonic()
                    delta = end - start
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=c.file_unique_id,
                            job_id=c.job_id,
                            context=Context.KBGEN_SUCCEEDED,
                            original_filename=c.original_filename,
                            language=c.language,
                            duration=timedelta(seconds=delta)
                        )
                    )
                    return json.loads(dhscanner_ast)['actualCallables']

        except aiohttp.ClientError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=c.file_unique_id,
                job_id=c.job_id,
                context=Context.KBGEN_FAILED,
                original_filename=c.original_filename,
                language=c.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_ith_callablle_file(
        self,
        c: CallablesMetadata,
        i: int
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:

        f = FileMetadata(
            f'{c.callable_unique_id}.callable.{i}',
            c.job_id,
            c.original_filename,
            c.language
        )

        if code := await self.the_storage_guy.load_file(f):
            return { 'source': (c.original_filename, code) }

        return None
