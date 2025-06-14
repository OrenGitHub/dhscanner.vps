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

BASEDIR: typing.Final[pathlib.Path] = pathlib.Path('/tmp/dhscanner_jobs')

class LocalStorage(interface.Storage):

    @typing.override
    async def save_file(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        start = time.monotonic()
        job_dir = LocalStorage.mk_jobdir_if_needed(job_id)
        if language := LocalStorage.get_language_from(original_filename_in_repo):
            stored_filename = LocalStorage.mk_stored_filename(job_dir, language)
            await LocalStorage.save_on_disk(content, stored_filename)
            LocalStorage.store_file_metadata_in_db(
                models.FileMetadata(
                    str(stored_filename),
                    job_id,
                    original_filename_in_repo,
                    language
                )
            )
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=str(stored_filename),
                    job_id=job_id,
                    context=Context.UPLOAD_FILE,
                    original_filename=original_filename_in_repo,
                    language=language,
                    duration=timedelta(seconds=delta)
                )
            )
            return

        await self.logger.info(
            LogMessage(
                file_unique_id=LocalStorage.get_unique_id(),
                job_id=job_id,
                context=Context.UPLOAD_FILE,
                original_filename=original_filename_in_repo,
                language=Language.UNKNOWN,
                duration=timedelta(0)
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

        native_ast = f'{f.stored_filename}.native.ast'
        async with aiofiles.open(native_ast, 'wt') as fl:
            await fl.write(content)
        
        LocalStorage.store_native_ast_metadata_in_db(
            models.NativeAstMetadata(
                native_ast,
                f.job_id,
                f.original_filename,
                f.language
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
                        file_unique_id=a.file_unique_id,
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
            await asyncio.to_thread(os.remove, a.file_unique_id)
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
    async def save_dhscanner_ast(self, content: str, f: models.NativeAstMetadata) -> None:

        native_ast = f'{f.stored_filename}.native.ast'
        async with aiofiles.open(native_ast, 'wt') as fl:
            await fl.write(content)
        
        LocalStorage.store_native_ast_metadata_in_db(
            models.NativeAstMetadata(
                native_ast,
                f.job_id,
                f.original_filename,
                f.language
            )
        )

    @typing.override
    async def load_dhscanner_ast(self, a: models.DhscannerAstMetadata) -> typing.Optional[bytes]:
        try:
            start = time.monotonic()
            async with aiofiles.open(a.native_ast_unique_id, 'rb') as fl:
                content = await fl.read()
                end = time.monotonic()
                delta = end - start
                await self.logger.warning(
                    LogMessage(
                        file_unique_id=a.file_unique_id,
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
    async def delete_dhscanner_ast(self, a: models.DhscannerAstMetadata) -> None:
        try:
            start = time.monotonic()
            await asyncio.to_thread(os.remove, a.file_unique_id)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=a.file_unique_id,
                    job_id=a.job_id,
                    context=Context.DELETE_DHSCANNER_AST_FILE_SUCCEEDED,
                    original_filename=a.original_filename,
                    language=a.language,
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
                file_unique_id=a.dhscanner_ast_unique_id,
                job_id=a.job_id,
                context=Context.DELETE_DHSCANNER_AST_FILE_FAILED,
                original_filename=a.original_filename,
                language=a.language,
                duration=timedelta(seconds=delta)
            )
        )

    @typing.override
    async def save_callables(self, content: dict, a: models.DhscannerAstMetadata) -> None:

        num_callables = len(list(content.keys()))
        for i in range(num_callables):
            callable = f'{a.dhscanner_ast_unique_id}.callable.{i}'
            async with aiofiles.open(callable, 'wt') as fl:
                json.dump(content, fl)
        
        LocalStorage.store_callables_metadata_in_db(
            models.CallablesMetadata(
                a.dhscanner_ast_unique_id,
                num_callables,
                a.job_id,
                a.original_filename,
                a.language
            )
        )

    @typing.override
    async def load_callables(self, c: models.CallablesMetadata) -> typing.Optional[dict]:

        callables = {}
        for i in range(c.num_callables):
            callable = f'{c.dhscanner_ast_unique_id}.callable.{i}'
            async with aiofiles.open(callable, 'rt') as fl:
                content = await fl.read()
                callables[callable] = content

        return callables

    @typing.override
    async def delete_callables(self, c: models.CallablesMetadata) -> None:
        try:
            start = time.monotonic()
            for i in range(c.num_callables):
                callable = f'{c.callable_unique_id}.callable.{i}'
                await asyncio.to_thread(os.remove, callable)
            end = time.monotonic()
            delta = end - start
            await self.logger.info(
                LogMessage(
                    file_unique_id=c.file_unique_id,
                    job_id=c.job_id,
                    context=Context.DELETE_CALLABLES_FILES_SUCCEEDED,
                    original_filename=c.original_filename,
                    language=c.language,
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
                file_unique_id=c.dhscanner_ast_unique_id,
                job_id=c.job_id,
                context=Context.DELETE_CALLABLES_FILES_FAILED,
                original_filename=c.original_filename,
                language=c.language,
                duration=timedelta(seconds=delta)
            )
        )

    @staticmethod
    def mk_jobdir_if_needed(job_id: str) -> pathlib.Path:
        job_dir = BASEDIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @staticmethod
    def get_unique_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def get_language_from(filename: str) -> typing.Optional[Language]:
        if language := Language.from_raw_str(pathlib.Path(filename).suffix):
            return language
        
        return None

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
