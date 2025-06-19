import json
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from workers.interface import AbstractWorker
from logger.models import Context, LogMessage
from storage.models import DhscannerAstMetadata

TO_CODEGEN_URL = 'http://codegen:3000/codegen'

@dataclasses.dataclass(frozen=True)
class Codegen(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        dhscanner_asts = self.the_storage_guy.load_dhscanner_asts_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as s:
            tasks = [self.codegen_single_dhscanner_ast(s, d) for d in dhscanner_asts]
            await asyncio.gather(*tasks)

    async def codegen_single_dhscanner_ast(
        self,
        session: aiohttp.ClientSession,
        a: DhscannerAstMetadata
    ) -> None:

        if dhscanner_ast := await self.read_dhscanner_ast_file(a):
            if content := await self.codegen(session, dhscanner_ast, a):
                if 'actualCallables' in content:
                    callables = content['actualCallables']
                    await self.the_storage_guy.save_callables(callables, a)
                    await self.the_storage_guy.delete_dhscanner_ast(a)

    async def codegen(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        a: DhscannerAstMetadata
    ) -> typing.Optional[dict]:
        start = time.monotonic()
        try:
            async with session.post(TO_CODEGEN_URL, data=code) as response:
                if response.status == 200:
                    callables = await response.text()
                    end = time.monotonic()
                    delta = end - start
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=a.file_unique_id,
                            job_id=a.job_id,
                            context=Context.CODEGEN_SUCCEEDED,
                            original_filename=a.original_filename,
                            language=a.language,
                            duration=timedelta(seconds=delta)
                        )
                    )
                    return json.loads(callables)

        except aiohttp.ClientError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=a.file_unique_id,
                job_id=a.job_id,
                context=Context.CODEGEN_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_dhscanner_ast_file(
        self, a: DhscannerAstMetadata
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:
        if code := await self.the_storage_guy.load_dhscanner_ast(a):
            return { 'source': (a.original_filename, code) }

        return None
