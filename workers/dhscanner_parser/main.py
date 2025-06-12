import time
import typing
import aiohttp
import asyncio
import aiofiles
import dataclasses

from datetime import timedelta

import storage

from logger.models import (
    Context,
    LogMessage
)

from common.language import Language
from storage.models import AstMetadata, FileMetadata
from workers.interface import AbstractWorker

DHSCANNER_AST_BUILDER_URL = {
    Language.JS: 'http://parsers:3000/from/js/to/dhscanner/ast',
    Language.TS: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.TSX: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.PHP: 'http://parsers:3000/from/php/to/dhscanner/ast',
    Language.PY: 'http://parsers:3000/from/py/to/dhscanner/ast',
    Language.RB: 'http://parsers:3000/from/rb/to/dhscanner/ast',
    Language.CS: 'http://parsers:3000/from/cs/to/dhscanner/ast',
    Language.GO: 'http://parsers:3000/from/go/to/dhscanner/ast',
}

@dataclasses.dataclass(frozen=True)
class DhscannerParser(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        asts = self.the_storage_guy.load_asts_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            tasks = [self.run_single_ast(session, f) for f in asts]
            await asyncio.gather(*tasks)

    async def run_single_ast(
        self,
        session: aiohttp.ClientSession,
        f: FileMetadata
    ) -> None:
        if native_ast := await self.read_native_ast_file(f):
            if content := await self.parse(session, native_ast, f):
                await storage.store_dhscanner_ast(content, f)

    async def parse(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        f: FileMetadata
    ) -> typing.Optional[str]:
        start = time.monotonic()
        url = DHSCANNER_AST_BUILDER_URL[f.language]
        try:
            async with session.post(url, data=code) as response:
                if response.status == 200:
                    end = time.monotonic()
                    delta = end - start
                    dhscanner_ast = await response.text()
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=f.file_unique_id,
                            job_id=f.job_id,
                            context=Context.DHSCANNER_PARSING_SUCCEEDED,
                            original_filename=f.original_filename,
                            language=f.language,
                            duration=timedelta(seconds=delta)
                        )
                    )
                    return dhscanner_ast

        except aiohttp.ClientError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=f.file_unique_id,
                job_id=f.job_id,
                context=Context.DHSCANNER_PARSER_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta)
            )
        )

    async def read_native_ast_file(self, f: AstMetadata) -> dict[str, typing.Tuple[str, bytes]]:
        if code := await self.the_storage_guy.load_file(f):
            return { 'source': (f.original_filename, code) }
