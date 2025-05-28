from __future__ import annotations

import abc
import enum
import typing
import dataclasses

from datetime import (
    datetime,
    timedelta
)

from language import Language

class StatusKind(str, enum.Enum):

    StatusAnalysisStarted = 'AnalysisStarted'
    StatusNativeParsingFinished = 'StatusNativeParsingFinished'
    StatusDhscannerParsingFinished = 'StatusDhscannerParsingFinished'
    StatusCodegenFinished = 'StatusCodegenFinished'
    StatusKbgenFinished = 'StatusKbgenFinished'
    StatusQueryengineFinished = 'StatusQueryengineFinished'
    StatusSarifGenerationFinished = 'StatusSarifGenerationFinished'

    @staticmethod
    def from_raw_string(raw: str) -> typing.Optional[StatusKind]:
        try:
            return StatusKind(raw)
        except ValueError:
            return None

@dataclasses.dataclass(frozen=True)
class Status(abc.ABC):

    @abc.abstractmethod
    def __init__(self) -> None:
        ...

    kind: StatusKind = dataclasses.field(init=False)
    job_id: str = dataclasses.field(init=False)

    @staticmethod
    def concrete_deserialization(kind: StatusKind) -> typing.Callable[[dict], typing.Optional[Status]]:
        match (kind):
            case StatusKind.StatusAnalysisStarted:
                return AnalysisStarted.deserialization
            case StatusKind.StatusNativeParsingFinished:
                return NativeParsingFinished.deserialization
            case StatusKind.StatusDhscannerParsingFinished:
                return DhscannerParsingFinished.deserialization
            case StatusKind.StatusCodegenFinished:
                return CodegenFinished.deserialization
            case StatusKind.StatusKbgenFinished:
                return KbgenFinished.deserialization
            case StatusKind.StatusQueryengineFinished:
                return QueryengineFinished.deserialization
            case StatusKind.StatusSarifGenerationFinished:
                return SarifGenerationFinished.deserialization

        return lambda d: None

    @staticmethod
    def from_dict(content: dict) -> typing.Optional[Status]:
        if 'kind' not in content:
            return None
        
        if kind := StatusKind.from_raw_string(content['kind']):
            deserialization_func = Status.concrete_deserialization(kind)
            return deserialization_func(content)
        
        return None
    
    def wait_for_step_0_native_parsing(self) -> bool:
        return False

    def wait_for_step_1_dhscanner_parsing(self) -> bool:
        return False

    def wait_for_step_2_code_generation(self) -> bool:
        return False

    def wait_for_step_3_knowledge_base_generation(self) -> bool:
        return False

    def wait_for_step_4_query_engine(self) -> bool:
        return False

@dataclasses.dataclass(frozen=True, kw_only=True)
class StatsLanguage:

    total_num_files: int
    parsed_correctly: int
    started: datetime
    finished: datetime
    overall_time: timedelta
    avg_time_per_file: timedelta

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[StatsLanguage]:

        if 'total_num_files' not in content:
            return None

        if 'parsed_correctly' not in content:
            return None

        if 'started' not in content:
            return None

        if 'finished' not in content:
            return None

        if 'avg_time_per_file' not in content:
            return None
        
        try:
            total_num_files = int(content['total_num_files'])
        except ValueError:
            return None

        try:
            parsed_correctly = int(content['parsed_correctly'])
        except ValueError:
            return None
        
        try:
            started = datetime.fromisoformat(content['started'])
        except ValueError:
            return None

        try:
            finished = datetime.fromisoformat(content['finished'])
        except ValueError:
            return None

        overall_time = finished - started
        avg_time_per_file = timedelta(0) if total_num_files == 0 else overall_time / total_num_files

        return StatsLanguage(
            total_num_files=total_num_files,
            parsed_correctly=parsed_correctly,
            started=started,
            finished=finished,
            overall_time=overall_time,
            avg_time_per_file=avg_time_per_file
        )


@dataclasses.dataclass(frozen=True)
class Stats:

    content: dict[Language, StatsLanguage]

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Stats]:

        data = {}
        for candidate_lang, candidate_stats in content.items():
            if language := Language.from_raw_str(candidate_lang):
                if stats := StatsLanguage.deserialization(candidate_stats):
                    data[language] = stats
                    continue
            return None

        return Stats(data)

@dataclasses.dataclass(frozen=True)
class AnalysisStarted(Status):

    start: datetime
    kind: StatusKind = dataclasses.field(
        init=False,
        default=StatusKind.StatusAnalysisStarted
    )

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'start' not in content:
            return None
        
        return AnalysisStarted(content['start'])
    
    @typing.override
    def wait_for_step_0_native_parsing(self) -> bool:
        return True

@dataclasses.dataclass(frozen=True)
class NativeParsingFinished(Status):

    stats: Stats
    kind: StatusKind = dataclasses.field(
        init=False,
        default=StatusKind.StatusNativeParsingFinished
    )

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'stats' not in content:
            return None
        
        if stats := Stats.deserialization(content['stats']):
            return NativeParsingFinished(stats)
        
        return None

@dataclasses.dataclass(frozen=True)
class DhscannerParsingFinished(Status):

    stats: Stats
    kind: StatusKind = dataclasses.field(
        init=False,
        default=StatusKind.StatusDhscannerParsingFinished
    )

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'stats' not in content:
            return None
        
        if stats := Stats.deserialization(content['stats']):
            return DhscannerParsingFinished(stats)
        
        return None

@dataclasses.dataclass(frozen=True)
class CodegenFinished(Status):

    num_callables: int

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'num_callables' not in content:
            return None
        
        return CodegenFinished(content['num_callables'])

@dataclasses.dataclass(frozen=True)
class KbgenFinished(Status):

    num_facts: int

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'num_facts' not in content:
            return None
        
        return KbgenFinished(content['num_facts'])

@dataclasses.dataclass(frozen=True)
class QueryengineFinished(Status):

    num_queries: int

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'num_queries' not in content:
            return None
        
        return QueryengineFinished(content['num_queries'])

@dataclasses.dataclass(frozen=True)
class SarifGenerationFinished(Status):

    num_flows: int

    @staticmethod
    def deserialization(content: dict) -> typing.Optional[Status]:
        if 'num_flows' not in content:
            return None
        
        return SarifGenerationFinished(content['num_flows'])

@dataclasses.dataclass(frozen=True)
class Coordinator(abc.ABC):

    @abc.abstractmethod
    def get_status(self, job_id: str) -> typing.Optional[Status]:
        ...

    @abc.abstractmethod
    def set_status(self, job_id: str, status: Status) -> None:
        ...

    @abc.abstractmethod
    def get_jobs_waiting_for_step_0_native_parsing(self) -> list[str]:
        ...

    @abc.abstractmethod
    def get_jobs_waiting_for_step_1_dhscanner_parsing(self) -> list[str]:
        ...

    @abc.abstractmethod
    def get_jobs_waiting_for_step_2_code_generation(self) -> list[str]:
        ...

    @abc.abstractmethod
    def get_jobs_waiting_for_step_3_knwoledge_base_generation(self) -> list[str]:
        ...

    @abc.abstractmethod
    def get_jobs_waiting_for_step_4_query_engine(self) -> list[str]:
        ...
