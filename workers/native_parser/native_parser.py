import typing
import asyncio
import aiohttp
import aiofiles
import dataclasses

from common.language import Language
from workers.interface import AbstractWorker

import models
import storage

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
        files = storage.load_files_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            scan = NativeParser.scan_worthy
            tasks = [self.run_single_file(session, job_id, f) for f in files if scan(f)]
            await asyncio.gather(*tasks)

    async def run_single_file(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
        f: models.FileMetadata
    ) -> None:
        code = await NativeParser.read_source_file(f.file_unique_id)
        content = await NativeParser.parse(session, code, f)
        await storage.store_ast(content, f, job_id)

    @staticmethod
    async def parse(
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        f: models.FileMetadata
    ) -> typing.Optional[str]:
        url = AST_BUILDER_URL[f.language]
        async with session.post(url, data=code) as response:
            return await response.text()

    @staticmethod
    async def read_source_file(
        filename: str,
        original_filename: str
    ) -> dict[str, typing.Tuple[str, bytes]]:

        async with aiofiles.open(filename, 'rb') as f:
            code = await f.read()

        return { 'source': (original_filename, code) }

    # TODO: adjust other reasons for exclusion
    # the reasons might depend on the language
    # (like the third party directory name: node_module for javascript,
    # site-packages for python or vendor/bundle for ruby etc.)
    # pylint: disable=unused-argument
    @staticmethod
    def scan_worthy(f: models.FileMetadata) -> bool:

        if '/test/' in f.original_filename:
            return False

        if '.test.' in f.original_filename:
            return False

        return True
