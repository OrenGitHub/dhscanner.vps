import os
import json
import uuid
import time
import typing
import pathlib
import asyncio
import aiofiles

from datetime import timedelta

from storage import db
from storage import models

from storage import interface
from common.language import Language
from logger.models import (
    Context,
    LogMessage
)

BASEDIR: typing.Final[pathlib.Path] = pathlib.Path(
    '/app/transient_storage/dhscanner_jobs'
)

# pylint: disable=too-many-public-methods
class LocalStorage(interface.Storage):

    @typing.override
    async def save_file(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str,
        gomod: typing.Optional[str]
    ) -> None:
        start = time.monotonic()
        job_dir = LocalStorage.mk_jobdir_if_needed(job_id)
        if language := Language.from_filename(original_filename_in_repo):
            stored_filename = LocalStorage.mk_stored_filename(job_dir, language)
            await LocalStorage.save_on_disk(content, stored_filename)
            LocalStorage.store_file_metadata_in_db(
                models.FileMetadata(
                    file_unique_id=str(stored_filename),
                    job_id=job_id,
                    original_filename=original_filename_in_repo,
                    language=language,
                    module_name_resolver=gomod
                )
            )
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=str(stored_filename),
                    job_id=job_id,
                    context=Context.UPLOADED_FILE_SAVED,
                    original_filename=original_filename_in_repo,
                    language=language,
                    duration=timedelta(seconds=delta)
                )
            )
            return

        end = time.monotonic()
        delta = end - start
        await self.logger.info(
            LogMessage(
                file_unique_id=LocalStorage.get_unique_id(),
                job_id=job_id,
                context=Context.UPLOADED_FILE_SKIPPED_UNKNOWN_LANGUAGE,
                original_filename=original_filename_in_repo,
                language=Language.UNKNOWN,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def load_file(self, f: models.FileMetadata) -> typing.Optional[bytes]:
        try:
            start = time.monotonic()
            async with aiofiles.open(f.file_unique_id, 'rb') as fl:
                content = await fl.read()
                end = time.monotonic()
                delta = end - start
                await self.logger.info(
                    LogMessage(
                        file_unique_id=f.file_unique_id,
                        job_id=f.job_id,
                        context=Context.READ_SOURCE_FILE_SUCCEEDED,
                        original_filename=f.original_filename,
                        language=f.language,
                        duration=timedelta(seconds=delta)
                    )
                )
                return content

        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=f.file_unique_id,
                job_id=f.job_id,
                context=Context.READ_SOURCE_FILE_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta)
            )
        )

        return None

    @typing.override
    async def delete_file(self, f: models.FileMetadata) -> None:
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, f.file_unique_id)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=f.file_unique_id,
                    job_id=f.job_id,
                    context=Context.DELETE_SOURCE_FILE_SUCCEEDED,
                    original_filename=f.original_filename,
                    language=f.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=f.file_unique_id,
                job_id=f.job_id,
                context=Context.DELETE_SOURCE_FILE_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_native_ast(self, content: str, f: models.FileMetadata) -> None:

        native_ast = f'{f.file_unique_id}.native.ast'
        async with aiofiles.open(native_ast, 'wt') as fl:
            await fl.write(content)

        LocalStorage.store_native_ast_metadata_in_db(
            models.NativeAstMetadata(
                native_ast_unique_id=native_ast,
                job_id=f.job_id,
                original_filename=f.original_filename,
                language=f.language,
                module_name_resolver=f.module_name_resolver
            )
        )

    @typing.override
    async def load_native_ast(self, a: models.NativeAstMetadata) -> typing.Optional[bytes]:
        try:
            start = time.monotonic()
            async with aiofiles.open(a.native_ast_unique_id, 'rb') as fl:
                content = await fl.read()
                end = time.monotonic()
                delta = end - start
                await self.logger.warning(
                    LogMessage(
                        file_unique_id=a.native_ast_unique_id,
                        job_id=a.job_id,
                        context=Context.READ_NATIVE_AST_FILE_SUCCEEDED,
                        original_filename=a.original_filename,
                        language=a.language,
                        duration=timedelta(seconds=delta)
                    )
                )
                return content

        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=a.file_unique_id,
                job_id=a.job_id,
                context=Context.READ_NATIVE_AST_FILE_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

        return None

    @typing.override
    async def delete_native_ast(self, a: models.NativeAstMetadata) -> None:
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, a.native_ast_unique_id)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=a.native_ast_unique_id,
                    job_id=a.job_id,
                    context=Context.DELETE_NATIVE_AST_FILE_SUCCEEDED,
                    original_filename=a.original_filename,
                    language=a.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=a.native_ast_unique_id,
                job_id=a.job_id,
                context=Context.DELETE_NATIVE_AST_FILE_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_dhscanner_ast(self, content: dict, a: models.NativeAstMetadata) -> None:

        unique_file_id = a.native_ast_unique_id.removesuffix('.native.ast')
        dhscanner_ast = f'{unique_file_id}.dhscanner.ast'
        async with aiofiles.open(dhscanner_ast, 'wt') as fl:
            content_as_str = json.dumps(content)
            await fl.write(content_as_str)

        LocalStorage.store_dhscanner_ast_metadata_in_db(
            models.DhscannerAstMetadata(
                dhscanner_ast_unique_id=dhscanner_ast,
                job_id=a.job_id,
                original_filename=a.original_filename,
                language=a.language
            )
        )

    @typing.override
    async def load_dhscanner_ast(self, a: models.DhscannerAstMetadata) -> typing.Optional[str]:
        try:
            start = time.monotonic()
            async with aiofiles.open(a.dhscanner_ast_unique_id, 'rt', encoding='utf-8') as fl:
                content = await fl.read()
                end = time.monotonic()
                delta = end - start
                await self.logger.warning(
                    LogMessage(
                        file_unique_id=a.dhscanner_ast_unique_id,
                        job_id=a.job_id,
                        context=Context.READ_DHSCANNER_AST_FILE_SUCCEEDED,
                        original_filename=a.original_filename,
                        language=a.language,
                        duration=timedelta(seconds=delta)
                    )
                )
                return content

        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=a.dhscanner_ast_unique_id,
                job_id=a.job_id,
                context=Context.READ_DHSCANNER_AST_FILE_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

        return None

    @typing.override
    async def delete_dhscanner_ast(self, a: models.DhscannerAstMetadata) -> None:
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, a.dhscanner_ast_unique_id)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=a.dhscanner_ast_unique_id,
                    job_id=a.job_id,
                    context=Context.DELETE_DHSCANNER_AST_FILE_SUCCEEDED,
                    original_filename=a.original_filename,
                    language=a.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=a.dhscanner_ast_unique_id,
                job_id=a.job_id,
                context=Context.DELETE_DHSCANNER_AST_FILE_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_callables(self, content: list[dict], a: models.DhscannerAstMetadata) -> None:

        for i, _callable in enumerate(content):
            unique_file_id = a.dhscanner_ast_unique_id.removesuffix('.dhscanner.ast')
            callable_name = f'{unique_file_id}.callable.{i}'
            async with aiofiles.open(callable_name, 'wt') as fl:
                content_as_str = json.dumps(_callable)
                await fl.write(content_as_str)

        LocalStorage.store_callables_metadata_in_db(
            models.CallablesMetadata(
                callable_unique_id=unique_file_id,
                num_callables=len(content),
                job_id=a.job_id,
                original_filename=a.original_filename,
                language=a.language
            )
        )

    @typing.override
    async def load_ith_callable(self, c: models.CallablesMetadata, i: int) -> typing.Optional[dict]:
        n = c.num_callables
        try:
            start = time.monotonic()
            fileanme = f'{c.callable_unique_id}.callable.{i}'
            async with aiofiles.open(fileanme, 'rt') as fl:
                content = await fl.read()
                _callable = json.loads(content)
                end = time.monotonic()
                delta = end - start
                await self.logger.warning(
                    LogMessage(
                        file_unique_id=c.callable_unique_id,
                        job_id=c.job_id,
                        context=Context.READ_CALLABLE_i_FILE_SUCCEEDED,
                        original_filename=c.original_filename,
                        language=c.language,
                        duration=timedelta(seconds=delta),
                        more_details=f'callable({i+1}/{n})'
                    )
                )
                return _callable

        except FileNotFoundError:
            pass
        except PermissionError:
            pass
        except json.JSONDecodeError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=c.callable_unique_id,
                job_id=c.job_id,
                context=Context.READ_CALLABLE_i_FILE_FAILED,
                original_filename=c.original_filename,
                language=c.language,
                duration=timedelta(seconds=delta),
                more_details=f'callable({i+1}/{n})'
            )
        )

        return None

    @typing.override
    async def delete_ith_callable(self, c: models.CallablesMetadata, i: int) -> None:
        try:
            start = time.monotonic()
            _callable = f'{c.callable_unique_id}.callable.{i}'
            await asyncio.to_thread(os.remove, _callable)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=c.callable_unique_id,
                    job_id=c.job_id,
                    context=Context.DELETE_CALLABLE_i_SUCCEEDED,
                    original_filename=c.original_filename,
                    language=c.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=c.callable_unique_id,
                job_id=c.job_id,
                context=Context.DELETE_CALLABLE_i_FAILED,
                original_filename=c.original_filename,
                language=c.language,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_knowledge_base_facts(self, content: list[str], c: models.CallablesMetadata, i: int) -> None:

        facts_filename = f'{c.callable_unique_id}.callable.{i}.facts'
        async with aiofiles.open(facts_filename, 'wt') as fl:
            await fl.write('\n'.join(content))

        LocalStorage.store_kbgen_facts_metadata_in_db(
            models.FactsMetadata(
                facts_unique_id=facts_filename,
                job_id=c.job_id,
                original_filename=c.original_filename,
                language=c.language
            )
        )

    @typing.override
    async def load_knowledge_base_facts(self, f: models.FactsMetadata) -> list[str]:
        start = time.monotonic()
        async with aiofiles.open(f.facts_unique_id, 'rt') as fl:
            lines = await fl.readlines()
            end = time.monotonic()
            delta = end - start
            await self.logger.warning(
                LogMessage(
                    file_unique_id=f.facts_unique_id,
                    job_id=f.job_id,
                    context=Context.READ_FACTS_FILE_SUCCEEDED,
                    original_filename=f.original_filename,
                    language=f.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return lines

    @typing.override
    async def delete_knowledge_base_facts(self, f: models.FactsMetadata) -> None:
        emessage = 'none'
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, f.facts_unique_id)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=f.facts_unique_id,
                    job_id=f.job_id,
                    context=Context.DELETE_FACTS_FILE_SUCCEEDED,
                    original_filename=f.original_filename,
                    language=f.language,
                    duration=timedelta(seconds=delta)
                )
            )
            return
        except FileNotFoundError as e:
            emessage = str(e)
        except PermissionError as e:
            emessage = str(e)

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=f.facts_unique_id,
                job_id=f.job_id,
                context=Context.DELETE_FACTS_FILE_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta),
                more_details=f'exception(s): {emessage}'
            )
        )

    @typing.override
    async def save_results(self, content: str, job_id: str) -> None:
        results = LocalStorage.jobdir(job_id) / 'results.txt'
        async with aiofiles.open(results, 'wt') as fl:
            await fl.write(content)

        results_as_str = str(results)
        LocalStorage.store_results_metadata_in_db(
            models.ResultsMetadata(
                results=results_as_str,
                job_id=job_id
            )
        )

    @typing.override
    async def load_results(self, r: models.ResultsMetadata) -> str:
        async with aiofiles.open(r.results, 'rt') as fl:
            return await fl.read()

    @typing.override
    async def delete_results(self, r: models.ResultsMetadata) -> None:
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, r.results)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=r.results,
                    job_id=r.job_id,
                    context=Context.DELETE_RESULTS_SUCCEEDED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta)
                )
            )
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

        end = time.monotonic()
        delta = end - start
        await self.logger.warning(
            LogMessage(
                file_unique_id=r.results,
                job_id=r.job_id,
                context=Context.DELETE_RESULTS_FAILED,
                original_filename='*',
                language=Language.ALL,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_output(self, content: dict, job_id: str) -> None:
        filename = LocalStorage.jobdir(job_id) / 'output.json'
        async with aiofiles.open(filename, 'wt') as fl:
            str_content = json.dumps(content)
            await fl.write(str_content)

    @typing.override
    async def load_output(self, job_id: str) -> dict:
        filename = LocalStorage.jobdir(job_id) / 'output.json'
        async with aiofiles.open(filename, 'rt') as fl:
            content = await fl.read()
            return json.loads(content)

    @typing.override
    async def delete_output(self, job_id: str) -> None:
        filename = LocalStorage.jobdir(job_id) / 'output.json'
        await asyncio.to_thread(os.remove, filename)

    @staticmethod
    def jobdir(job_id: str) -> pathlib.Path:
        return BASEDIR / job_id

    @staticmethod
    def mk_jobdir_if_needed(job_id: str) -> pathlib.Path:
        job_dir = LocalStorage.jobdir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @staticmethod
    def get_unique_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def mk_stored_filename(job_dir: pathlib.Path, language: Language) -> pathlib.Path:
        unique_id = LocalStorage.get_unique_id()
        return job_dir / f'{unique_id}.{language.value}'

    @staticmethod
    async def save_on_disk(
        content: typing.AsyncIterator[bytes],
        stored_filename: pathlib.Path,
    ) -> None:
        async with aiofiles.open(stored_filename, 'wb') as fl:
            async for chunk in content:
                await fl.write(chunk)

    @staticmethod
    def store_file_metadata_in_db(f: models.FileMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(f)
            session.commit()

    @staticmethod
    def store_native_ast_metadata_in_db(a: models.NativeAstMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(a)
            session.commit()

    @staticmethod
    def store_dhscanner_ast_metadata_in_db(a: models.DhscannerAstMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(a)
            session.commit()

    @staticmethod
    def store_callables_metadata_in_db(c: models.CallablesMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(c)
            session.commit()

    @staticmethod
    def store_kbgen_facts_metadata_in_db(c: models.FactsMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(c)
            session.commit()

    @staticmethod
    def store_results_metadata_in_db(r: models.ResultsMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(r)
            session.commit()
