import uuid
import typing
import pathlib
import aiofiles
import sqlalchemy

import db
import models
from language import Language


BASEDIR: typing.Final[pathlib.Path] = pathlib.Path('/tmp/dhscanner_jobs')

def mk_jobdir_if_needed(job_id: str) -> pathlib.Path:
    job_dir = BASEDIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def get_unique_id() -> str:
    return str(uuid.uuid4())

def get_suffix_from(filename: str) -> str:
    return pathlib.Path(filename).suffix or '.unknown'

def mk_stored_filename(job_dir: pathlib.Path, suffix: str) -> pathlib.Path:
    unique_id = get_unique_id()
    return job_dir / f'{unique_id}{suffix}'

async def store_file(content: typing.AsyncIterator[bytes], original_filename_in_repo: str, job_id: str) -> None:
    job_dir = mk_jobdir_if_needed(job_id)
    suffix = get_suffix_from(original_filename_in_repo)
    stored_filename = mk_stored_filename(job_dir, suffix)
    await store_content_as_file_on_disk(content, stored_filename)
    store_file_metadata_in_db(stored_filename, original_filename_in_repo, suffix, job_id)

async def store_content_as_file_on_disk(
    content: typing.AsyncIterator[bytes],
    stored_filename: pathlib.Path,
) -> None:

    async with aiofiles.open(stored_filename, "wb") as fl:
        async for chunk in content:
            await fl.write(chunk)

def store_file_metadata_in_db(
    stored_filename: pathlib.Path,
    original_filename_in_repo: str,
    suffix: str,
    job_id: str
) -> None:

    if language := Language.from_raw_str(suffix):

        session = db.SessionLocal()
        stmt = sqlalchemy.insert(models.FILES).values(
            file_unique_id=stored_filename,
            job_id=job_id,
            original_filename=original_filename_in_repo,
            language=language
        )

        with db.SessionLocal() as session:
            session.execute(stmt)
            session.commit()
