import abc
import typing
import dataclasses

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