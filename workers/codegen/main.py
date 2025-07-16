import http
import json
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from coordinator.interface import Status
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

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForKbgen
            )

    async def codegen_single_dhscanner_ast(
        self,
        session: aiohttp.ClientSession,
        a: DhscannerAstMetadata
    ) -> None:

        if dhscanner_ast := await self.read_dhscanner_ast_file(a):
            if content := await self.codegen(session, dhscanner_ast, a):
                await self.the_storage_guy.save_callables(content, a)
        await self.the_storage_guy.delete_dhscanner_ast(a)

    async def codegen(
        self,
        session: aiohttp.ClientSession,
        dhscanner_ast: dict,
        a: DhscannerAstMetadata
    ) -> list[dict]:
        start = time.monotonic()
        try:
            async with session.post(TO_CODEGEN_URL, json=dhscanner_ast) as response:
                if response.status == http.HTTPStatus.OK:
                    callables = await response.json()
                    end = time.monotonic()
                    delta = end - start
                    if 'actualCallables' in callables:
                        actualCallables = callables['actualCallables']
                        if isinstance(actualCallables, list):
                            n = len(actualCallables)
                            await self.the_logger_dude.info(
                                LogMessage(
                                    file_unique_id=a.dhscanner_ast_unique_id,
                                    job_id=a.job_id,
                                    context=Context.CODEGEN_SUCCEEDED,
                                    original_filename=a.original_filename,
                                    language=a.language,
                                    duration=timedelta(seconds=delta),
                                    more_details=f'callables({n})'
                                )
                            )
                            return actualCallables

        except aiohttp.ClientError:
            pass

        except json.JSONDecodeError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=a.dhscanner_ast_unique_id,
                job_id=a.job_id,
                context=Context.CODEGEN_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_dhscanner_ast_file(self, a: DhscannerAstMetadata) -> typing.Optional[dict]:
        if content := await self.the_storage_guy.load_dhscanner_ast(a):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        return None
