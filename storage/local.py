import uuid
import time
import typing
import pathlib
import aiofiles
import sqlalchemy

from datetime import timedelta

from . import db
from . import models

from storage import interface
from logger.client import Logger
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
            await Logger.info(
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

        await Logger.info(
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
    async def load_file(self, f: models.FileMetadata) -> bytes:
        async with aiofiles.open(f.file_unique_id, 'rb') as fl:
            return await fl.read()

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

    @typing.override
    async def save_ast(
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
            await Logger.info(
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

        await Logger.info(
            LogMessage(
                file_unique_id=LocalStorage.get_unique_id(),
                job_id=job_id,
                context=Context.UPLOAD_FILE,
                original_filename=original_filename_in_repo,
                language=Language.UNKNOWN,
                duration=timedelta(0)
            )
        )

    @staticmethod
    async def save_on_disk(
        content: typing.AsyncIterator[bytes],
        stored_filename: pathlib.Path,
    ) -> None:
        async with aiofiles.open(stored_filename, 'wb') as fl:
            async for chunk in content:
                await fl.write(chunk)

    @staticmethod
    def store_file_metadata_in_db(file_metadata: models.FileMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(file_metadata)
            session.commit()

    @staticmethod
    def store_ast_metadata_in_db(ast_metadata: models.AstMetadata) -> None:
        with db.SessionLocal() as session:
            session.add(ast_metadata)
            session.commit()
