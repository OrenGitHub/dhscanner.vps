import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from logger.models import (
    Context,
    LogMessage
)

from common.language import Language
from workers.interface import AbstractWorker
from storage.models import NativeAstMetadata

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
        a: NativeAstMetadata
    ) -> None:
        if native_ast := await self.read_native_ast_file(a):
            if content := await self.parse(session, native_ast, a):
                await self.the_storage_guy.save_dhscanner_ast(content, a)

    async def parse(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        a: NativeAstMetadata
    ) -> typing.Optional[str]:
        start = time.monotonic()
        url = DHSCANNER_AST_BUILDER_URL[a.language]
        try:
            async with session.post(url, data=code) as response:
                if response.status == 200:
                    end = time.monotonic()
                    delta = end - start
                    dhscanner_ast = await response.text()
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=a.file_unique_id,
                            job_id=a.job_id,
                            context=Context.DHSCANNER_PARSING_SUCCEEDED,
                            original_filename=a.original_filename,
                            language=a.language,
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
                file_unique_id=a.file_unique_id,
                job_id=a.job_id,
                context=Context.DHSCANNER_PARSER_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

    async def read_native_ast_file(
        self, a: NativeAstMetadata
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:
        if code := await self.the_storage_guy.load_native_ast(a):
            return { 'source': (a.original_filename, code) }
        
        return None
