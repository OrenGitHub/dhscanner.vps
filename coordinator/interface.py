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
    StatusSarifGenerationFinished = 'StatusSarifGenerationFinished'

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
    async def get_jobs_waiting_for(self, desired_status: Status) -> list[str]:
        ...

    @abc.abstractmethod
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        ...
