import http
import time
import typing
import asyncio
import aiohttp
import dataclasses

from datetime import timedelta

from common.language import Language
from coordinator.interface import Status
from storage.models import FileMetadata
from logger.models import Context, LogMessage
from workers.interface import AbstractWorker

AST_BUILDER_URL = {
    Language.JS: 'http://frontjs:3000/to/esprima/js/ast',
    Language.TS: 'http://frontts:3000/to/native/ts/ast',
    Language.TSX: 'http://frontts:3000/to/native/ts/ast',
    Language.PHP: 'http://frontphp:5000/to/php/ast',
    Language.PY: 'http://frontpy:5000/to/native/py/ast',
    Language.RB: 'http://frontrb:3000/to/native/cruby/ast',
    Language.CS: 'http://frontcs:8080/to/native/cs/ast',
    Language.GO: 'http://frontgo:8080/to/native/go/ast',
    Language.BLADE_PHP: 'http://frontphp:5000/to/php/code'
}

@dataclasses.dataclass(frozen=True)
class NativeParser(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        files = self.the_storage_guy.load_files_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            tasks = [self.run_single_file(session, f) for f in files]
            await asyncio.gather(*tasks)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForDhscannerParsing
            )

    async def run_single_file(
        self,
        session: aiohttp.ClientSession,
        f: FileMetadata
    ) -> None:

        if code := await self.read_source_file(f):
            if content := await self.parse(session, code, f):
                await self.the_storage_guy.save_native_ast(content, f)

            # either way - delete the source file ...
            await self.the_storage_guy.delete_file(f)

    async def parse(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        f: FileMetadata
    ) -> typing.Optional[str]:
        start = time.monotonic()
        url = AST_BUILDER_URL[f.language]
        try:
            form = aiohttp.FormData()
            form.add_field(
                'source',
                code['source'][1],
                filename=code['source'][0],
                content_type='application/octet-stream'
            )
            async with session.post(url, data=form) as response:
                if response.status == http.HTTPStatus.OK:
                    native_ast = await response.text()
                    context = Context.NATIVE_PARSING_SUCCEEDED
                    received_native_ast_is_empty = (len(native_ast) == 0)
                    if received_native_ast_is_empty:
                        context = Context.NATIVE_PARSING_EMPTY_AST
                    end = time.monotonic()
                    delta = end - start
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=f.file_unique_id,
                            job_id=f.job_id,
                            context=context,
                            original_filename=f.original_filename,
                            language=f.language,
                            duration=timedelta(seconds=delta)
                        )
                    )

                    if received_native_ast_is_empty:
                        return None

                    return native_ast

        except aiohttp.ClientError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=f.file_unique_id,
                job_id=f.job_id,
                context=Context.NATIVE_PARSING_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_source_file(
        self, f: FileMetadata
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:
        if code := await self.the_storage_guy.load_file(f):
            return { 'source': (f.original_filename, code) }

        return None
