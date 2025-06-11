import abc
import typing
import dataclasses

@dataclasses.dataclass(frozen=True)
class Storage(abc.ABC):

    @abc.abstractmethod
    async def save_file(
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_ast(
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_callable(
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_knowledge_base_facts(
        content: typing.AsyncIterator[bytes],
        original_filename_in_repo: str,
        job_id: str
    ) -> None:
        ...

    @abc.abstractmethod
    async def save_results(
        content: typing.AsyncIterator[bytes],
        job_id: str
    ) -> None:
        ...