import abc
import typing
import sqlalchemy
import dataclasses

from logger.client import Logger
from storage import db
from storage.models import (
    CallablesMetadata,
    DhscannerAstMetadata,
    FileMetadata,
    KbgenFactsMetadata,
    NativeAstMetadata,
)

@dataclasses.dataclass(frozen=True)
class Storage(abc.ABC):

    logger: Logger

    @abc.abstractmethod
    async def save_file(
        self,
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def load_file(self, f: FileMetadata) -> typing.Optional[bytes]:
        ...

    @abc.abstractmethod
    async def delete_file(self, f: FileMetadata) -> None:
        ...

    @abc.abstractmethod
    async def save_native_ast(self, content: str, f: FileMetadata) -> None:
        ...

    @abc.abstractmethod
    async def load_native_ast(self, a: NativeAstMetadata) -> typing.Optional[bytes]:
        ...

    @abc.abstractmethod
    async def delete_native_ast(self, a: NativeAstMetadata) -> None:
        ...

    @abc.abstractmethod
    async def save_dhscanner_ast(self, content: str, a: NativeAstMetadata) -> None:
        ...

    @abc.abstractmethod
    async def load_dhscanner_ast(self, a: DhscannerAstMetadata) -> typing.Optional[bytes]:
        ...

    @abc.abstractmethod
    async def delete_dhscanner_ast(self, a: DhscannerAstMetadata) -> None:
        ...

    @abc.abstractmethod
    async def save_callables(self, content: dict, a: DhscannerAstMetadata) -> None:
        ...

    @abc.abstractmethod
    async def load_callables(self, c: CallablesMetadata) -> typing.Optional[dict]:
        ...

    @abc.abstractmethod
    async def delete_callables(self, c: CallablesMetadata) -> None:
        ...

    @abc.abstractmethod
    async def save_knowledge_base_facts(self, content: list[str], c: CallablesMetadata) -> None:
        ...

    @abc.abstractmethod
    async def load_knowledge_base_facts(self, a: KbgenFactsMetadata) -> typing.Optional[str]:
        ...

    @abc.abstractmethod
    async def delete_knowledge_base_facts(self, a: KbgenFactsMetadata) -> None:
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

    @staticmethod
    def load_native_asts_metadata_from_db(job_id: str) -> list[NativeAstMetadata]:
        with db.SessionLocal() as session:
            condition_is_satisfied = NativeAstMetadata.job_id == job_id
            stmt = sqlalchemy.select(NativeAstMetadata).where(condition_is_satisfied)
            result = session.execute(stmt).scalars().all()
            return typing.cast(list[NativeAstMetadata], result)

    @staticmethod
    def load_dhscanner_asts_metadata_from_db(job_id: str) -> list[DhscannerAstMetadata]:
        with db.SessionLocal() as session:
            condition_is_satisfied = DhscannerAstMetadata.job_id == job_id
            stmt = sqlalchemy.select(DhscannerAstMetadata).where(condition_is_satisfied)
            result = session.execute(stmt).scalars().all()
            return typing.cast(list[DhscannerAstMetadata], result)

    @staticmethod
    def load_callables_metadata_from_db(job_id: str) -> list[CallablesMetadata]:
        with db.SessionLocal() as session:
            condition_is_satisfied = DhscannerAstMetadata.job_id == job_id
            stmt = sqlalchemy.select(DhscannerAstMetadata).where(condition_is_satisfied)
            result = session.execute(stmt).scalars().all()
            return typing.cast(list[DhscannerAstMetadata], result)
