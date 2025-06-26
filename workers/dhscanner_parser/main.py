from __future__ import annotations

import http
import json
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from coordinator.interface import Status
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

@dataclasses.dataclass(kw_only=True, frozen=True)
class Location:

    filename: str
    lineStart: int
    lineEnd: int
    colStart: int
    colEnd: int

    def __str__(self) -> str:
        return f'[{self.lineStart}:{self.colStart}-{self.lineEnd}:{self.colEnd}]'

    @staticmethod
    def from_dict(candidate: dict) -> typing.Optional[Location]:

        if 'filename' not in candidate:
            return None
        if 'lineStart' not in candidate:
            return None
        if 'lineEnd' not in candidate:
            return None
        if 'colStart' not in candidate:
            return None
        if 'colEnd' not in candidate:
            return None

        return Location(
            filename=candidate['filename'],
            lineStart=candidate['lineStart'],
            lineEnd=candidate['lineEnd'],
            colStart=candidate['colStart'],
            colEnd=candidate['colEnd']
        )

@dataclasses.dataclass(frozen=True)
class DhscannerParser(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        asts = self.the_storage_guy.load_native_asts_metadata_from_db(job_id)
        async with aiohttp.ClientSession() as session:
            tasks = [self.run_single_ast(session, f) for f in asts]
            await asyncio.gather(*tasks)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForCodegen
            )

    async def run_single_ast(
        self,
        session: aiohttp.ClientSession,
        a: NativeAstMetadata
    ) -> None:

        if native_ast := await self.read_native_ast_file(a):
            if content := await self.parse(session, native_ast, a):
                await self.the_storage_guy.save_dhscanner_ast(content, a)
        await self.the_storage_guy.delete_native_ast(a)

    async def parse(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        a: NativeAstMetadata
    ) -> typing.Optional[str]:
        start = time.monotonic()
        url = DHSCANNER_AST_BUILDER_URL[a.language]
        try:
            payload = {
                'filename': code['source'][0],
                'content': code['source'][1].decode('utf-8')
            }
            async with session.post(url, json=payload) as response:
                if response.status == http.HTTPStatus.OK:
                    dhscanner_ast = await response.json()
                    end = time.monotonic()
                    delta = end - start
                    context = Context.DHSCANNER_PARSING_SUCCEEDED
                    more_details = 'nothing else to add'
                    dhscanner_ast_as_string = json.dumps(dhscanner_ast)
                    corresponding_byte_size = len(dhscanner_ast_as_string)

                    if 'status' in dhscanner_ast and dhscanner_ast['status'] == 'FAILED':
                        context = Context.DHSCANNER_PARSING_FAILED
                        more_details = 'could not extract parse error location'
                        if 'location' in dhscanner_ast:
                            if location := Location.from_dict(dhscanner_ast['location']):
                                more_details = str(location)

                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=a.native_ast_unique_id,
                            job_id=a.job_id,
                            context=context,
                            original_filename=a.original_filename,
                            language=a.language,
                            duration=timedelta(seconds=delta),
                            more_details=more_details,
                            corresponding_byte_size=corresponding_byte_size
                        )
                    )

                    return dhscanner_ast

        except aiohttp.ClientError:
            pass

        except json.JSONDecodeError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=a.native_ast_unique_id,
                job_id=a.job_id,
                context=Context.DHSCANNER_PARSING_SYSTEM_FAILURE,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_native_ast_file(
        self, a: NativeAstMetadata
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:
        if code := await self.the_storage_guy.load_native_ast(a):
            return { 'source': (a.original_filename, code) }

        return None
