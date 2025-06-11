import typing
import aiohttp
import asyncio
import aiofiles
import dataclasses

import models
import storage

from common.language import Language
from abstract_worker import AbstractWorker

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

    async def run(self, job_id: str) -> None:
        asts = storage.load_asts_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            tasks = [self.run_single_ast(session, job_id, f) for f in asts]
            await asyncio.gather(*tasks)

    async def run_single_ast(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
        f: models.FileMetadata
    ) -> None:
        ast = await DhscannerParser.read_ast_file(f.file_unique_id)
        dhscanner_ast = await DhscannerParser.parse(session, ast, f)
        await storage.store_dhscanner_ast(dhscanner_ast, f, job_id)

    @staticmethod
    async def parse(
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        f: models.FileMetadata
    ) -> typing.Optional[str]:
        url = DHSCANNER_AST_BUILDER_URL[f.language]
        async with session.post(url, data=code) as response:
            return await response.text()

    @staticmethod
    async def read_ast_file(
        filename: str,
        original_filename: str
    ) -> dict[str, typing.Tuple[str, bytes]]:

        async with aiofiles.open(filename, 'rb') as f:
            ast = await f.read()

        return { 'source': (original_filename, ast) }
