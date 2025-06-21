from __future__ import annotations

import enum
import dataclasses

from datetime import timedelta
import typing

import sqlalchemy

from sqlalchemy.orm import DeclarativeBase # type: ignore[attr-defined]
from sqlalchemy.orm import Mapped # type: ignore[attr-defined]
from sqlalchemy.orm import mapped_column # type: ignore[attr-defined]

from common.language import Language

class Level(str, enum.Enum):
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'

class Context(str, enum.Enum):
    UPLOADED_FILE_RECEIVED = 'UPLOADED_FILE_RECEIVED'
    UPLOADED_FILE_SAVED = 'UPLOADED_FILE_SAVED'
    COORDINATOR_NOT_RESPONDING = 'COORDINATOR_NOT_RESPONDING'
    READ_SOURCE_FILE_FAILED = 'READ_SOURCE_FILE_FAILED'
    READ_SOURCE_FILE_SUCCEEDED = 'READ_SOURCE_FILE_SUCCEEDED'
    DELETE_SOURCE_FILE_FAILED = 'DELETE_SOURCE_FILE_FAILED'
    DELETE_SOURCE_FILE_SUCCEEDED = 'DELETE_SOURCE_FILE_SUCCEEDED'
    READ_NATIVE_AST_FILE_FAILED = 'READ_NATIVE_AST_FILE_FAILED'
    READ_NATIVE_AST_FILE_SUCCEEDED = 'READ_NATIVE_AST_FILE_SUCCEEDED'
    DELETE_NATIVE_AST_FILE_FAILED = 'DELETE_NATIVE_AST_FILE_FAILED'
    DELETE_NATIVE_AST_FILE_SUCCEEDED = 'DELETE_NATIVE_AST_FILE_SUCCEEDED'
    NATIVE_PARSING_SUCCEEDED = 'NATIVE_PARSING_SUCCEEDED'
    NATIVE_PARSING_FAILED = 'NATIVE_PARSING_FAILED'
    READ_DHSCANNER_AST_FILE_FAILED = 'READ_DHSCANNER_AST_FILE_FAILED'
    READ_DHSCANNER_AST_FILE_SUCCEEDED = 'READ_DHSCANNER_AST_FILE_SUCCEEDED'
    DELETE_DHSCANNER_AST_FILE_FAILED = 'DELETE_DHSCANNER_AST_FILE_FAILED'
    DELETE_DHSCANNER_AST_FILE_SUCCEEDED = 'DELETE_DHSCANNER_AST_FILE_SUCCEEDED'
    DHSCANNER_PARSING_SUCCEEDED = 'DHSCANNER_PARSING_SUCCEEDED'
    DHSCANNER_PARSER_FAILED = 'DHSCANNER_PARSER_FAILED'
    READ_CALLABLES_FILES_FAILED = 'READ_CALLABLES_FILES_FAILED'
    READ_CALLABLES_FILES_SUCCEEDED = 'READ_CALLABLES_FILES_SUCCEEDED'
    DELETE_CALLABLES_FILES_FAILED = 'DELETE_CALLABLES_FILES_FAILED'
    DELETE_CALLABLES_FILES_SUCCEEDED = 'DELETE_CALLABLES_FILES_SUCCEEDED'
    CODEGEN_SUCCEEDED = 'CODEGEN_SUCCEEDED'
    CODEGEN_FAILED = 'CODEGEN_FAILED'
    DELETE_KBGEN_FACTS_FILES_FAILED = 'DELETE_KBGEN_FACTS_FILES_FAILED'
    DELETE_KBGEN_FACTS_FILES_SUCCEEDED = 'DELETE_KBGEN_FACTS_FILES_SUCCEEDED'
    KBGEN_SUCCEEDED = 'KBGEN_SUCCEEDED'
    KBGEN_FAILED = 'KBGEN_FAILED'
    QUERYENGINE = 'QUERYENGINE'
    READ_RESULTS_FAILED = 'READ_RESULTS_FAILED'
    READ_RESULTS_SUCCEEDED = 'READ_RESULTS_SUCCEEDED'
    DELETE_RESULTS_FAILED = 'DELETE_RESULTS_FAILED'
    DELETE_RESULTS_SUCCEEDED = 'DELETE_RESULTS_SUCCEEDED'
    RESULTS = 'RESULTS'

# pylint: disable=too-few-public-methods
class Base(DeclarativeBase):
    pass

# pylint: disable=too-few-public-methods
@dataclasses.dataclass(kw_only=True)
class LogMessage(Base):

    __tablename__ = 'logs'

    file_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    context: Mapped[Context] = mapped_column(sqlalchemy.Enum(Context), nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)
    duration: Mapped[timedelta] = mapped_column(sqlalchemy.Interval, nullable=False)

    def tojson(self) -> dict:
        return {
            'file_unique_id': self.file_unique_id,
            'job_id': self.job_id,
            'context': self.context.value,
            'original_filename': self.original_filename,
            'language': self.language.value,
            'duration': self.duration.total_seconds()
        }

    @classmethod
    def fromjson(cls, content: dict) -> typing.Optional[LogMessage]:
        try:
            return cls(
                file_unique_id=content['file_unique_id'],
                job_id=content['job_id'],
                context=Context(content['context']),
                original_filename=content['original_filename'],
                language=Language(content['language']),
                duration=timedelta(seconds=content['duration'])
            )
        except KeyError: # missing field(s)
            return None
        except ValueError: # Enum(s) conversion failed
            return None
