from __future__ import annotations

import abc
import enum
import typing
import dataclasses

from logger.client import Logger

class Status(str, enum.Enum):

    WaitingForNativeParsing = 'WaitingForNativeParsing'
    WaitingForDhscannerParsing = 'WaitingForDhscannerParsing'
    WaitingForCodegen = 'WaitingForCodegen'
    WaitingForKbgen = 'WaitingForKbgen'
    WaitingForQueryengine = 'WaitingForQueryengine'
    WaitingForResultsGeneration = 'WaitingForResultsGeneration'
    Finished = 'Finished'

    @staticmethod
    def from_raw_string(raw: str) -> typing.Optional[Status]:
        try:
            return Status(raw)
        except ValueError:
            return None

@dataclasses.dataclass(frozen=True)
class Coordinator(abc.ABC):

    logger: Logger

    @abc.abstractmethod
    def get_status(self, job_id: str) -> typing.Optional[Status]:
        ...

    @abc.abstractmethod
    def set_status(self, job_id: str, status: Status) -> None:
        ...

    @abc.abstractmethod
    def get_agent_mode(self, job_id: str) -> bool:
        ...

    @abc.abstractmethod
    def set_agent_mode(self, job_id: str, agent_mode: bool) -> None:
        ...

    @abc.abstractmethod
    def get_kb_location(self, job_id: str) -> typing.Optional[str]:
        ...

    @abc.abstractmethod
    def set_kb_location(self, job_id: str, kb_location: str) -> None:
        ...

    @abc.abstractmethod
    async def get_jobs_waiting_for(self, desired_status: Status) -> list[str]:
        ...
