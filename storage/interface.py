import abc
import typing
import dataclasses

import sqlalchemy

from storage import db
from storage.models import FileMetadata

@dataclasses.dataclass(frozen=True)
class Storage(abc.ABC):

    @abc.abstractmethod
    async def save_file(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def load_file(self, f: FileMetadata) -> bytes:
        ...

    @abc.abstractmethod
    async def save_ast(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_callable(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_knowledge_base_facts(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_results(
        self,
        content: typing.AsyncIterator[bytes],
        job_id: str
    ) -> None:
        ...

    @staticmethod
    def load_files_metadata_from_db(job_id: str) -> list[FileMetadata]:
        with db.SessionLocal() as session:
            condition_is_satisfied = FileMetadata.job_id == job_id
            stmt = sqlalchemy.select(FileMetadata).where(condition_is_satisfied)
            result = session.execute(stmt).scalars().all()
            return typing.cast(list[FileMetadata], result)
