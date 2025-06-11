import dataclasses
import uuid
import typing
import pathlib
import aiofiles
import sqlalchemy

import db
import models
from common.language import Language


BASEDIR: typing.Final[pathlib.Path] = pathlib.Path('/tmp/dhscanner_jobs')

def mk_jobdir_if_needed(job_id: str) -> pathlib.Path:
    job_dir = BASEDIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def get_unique_id() -> str:
    return str(uuid.uuid4())

def get_language_from(filename: str) -> typing.Optional[Language]:
    if language := Language.from_raw_str(pathlib.Path(filename).suffix):
        return language
    
    return None

def mk_stored_filename(job_dir: pathlib.Path, language: Language) -> pathlib.Path:
    unique_id = get_unique_id()
    return job_dir / f'{unique_id}.{language.value}'

async def store_file(content: typing.AsyncIterator[bytes], original_filename_in_repo: str, job_id: str) -> None:
    job_dir = mk_jobdir_if_needed(job_id)
    language = get_language_from(original_filename_in_repo)
    stored_filename = mk_stored_filename(job_dir, language)
    await store_content_as_file_on_disk(content, stored_filename)
    file_metadata = models.FileMetadata(stored_filename, job_id, original_filename_in_repo, language)
    store_file_metadata_in_db(file_metadata)

async def store_ast(content: typing.AsyncIterator[bytes], original_filename_in_repo: str, job_id: str) -> None:
    job_dir = mk_jobdir_if_needed(job_id)
    language = get_language_from(original_filename_in_repo)
    stored_filename = mk_stored_filename(job_dir, language)
    await store_content_as_file_on_disk(content, stored_filename)
    file_metadata = models.FileMetadata(stored_filename, job_id, original_filename_in_repo, language)
    store_ast_metadata_in_db(file_metadata)

async def store_content_as_file_on_disk(
    content: typing.AsyncIterator[bytes],
    stored_filename: pathlib.Path,
) -> None:

    async with aiofiles.open(stored_filename, "wb") as fl:
        async for chunk in content:
            await fl.write(chunk)

def store_file_metadata_in_db(file_metadata: models.FileMetadata) -> None:

    if language := Language.from_raw_str(file_metadata.suffix):

        session = db.SessionLocal()
        stmt = sqlalchemy.insert(models.FILES).values(
            file_unique_id=file_metadata.stored_filename,
            job_id=file_metadata.job_id,
            original_filename=file_metadata.original_filename_in_repo,
            language=language
        )

        with db.SessionLocal() as session:
            session.execute(stmt)
            session.commit()

def load_files_metadata_from_db(job_id: str) -> list[models.FileMetadata]:
    with db.SessionLocal() as session:
        condition_is_satisfied = models.FILES.c.job_id == job_id
        stmt = sqlalchemy.select(models.FileMetadata).where(condition_is_satisfied)
        result = session.execute(stmt)
        return result.scalars().all()
