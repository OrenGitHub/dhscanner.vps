import abc
import enum
import typing
import asyncio
import dataclasses

from logger.client import Logger
from storage.interface import Storage
from coordinator.interface import Coordinator, Status

class JobDescription(str, enum.Enum):
    NATIVE_PARSER = 'NATIVE_PARSER'
    DHSCANNER_PARSER = 'DHSCANNER_PARSER'

@dataclasses.dataclass(frozen=True)
class AbstractWorker(abc.ABC):

    the_logger_dude: Logger
    the_storage_guy: Storage
    the_coordinator: Coordinator
    status: Status

    @typing.final
    def check_in(self) -> None:
        asyncio.run(self.worker_loop())

    @typing.final
    async def worker_loop(self) -> None:
        while True:
            job_ids = await self.the_coordinator.get_jobs_waiting_for(self.status)
            await self.worker_loop_internal(job_ids)
            await self.the_coordinator.mark_jobs_finished(job_ids)
            await asyncio.sleep(1)

    @typing.final
    async def worker_loop_internal(self, job_ids: list[str]) -> None:
        tasks = [self.run(job_id) for job_id in job_ids]
        await asyncio.gather(*tasks)

    @abc.abstractmethod
    async def run(self, job_id: str) -> None:
        ...
