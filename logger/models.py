import dataclasses
import enum

from datetime import timedelta

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
    UPLOAD_FILE = 'UPLOAD_FILE'
    READ_SOURCE_FILE_FAILED = 'READ_SOURCE_FILE_FAILED'
    READ_SOURCE_FILE_SUCCEEDED = 'READ_SOURCE_FILE_SUCCEEDED'
    NATIVE_PARSING_SUCCEEDED = 'NATIVE_PARSING_SUCCEEDED'
    NATIVE_PARSING_FAILED = 'NATIVE_PARSING_FAILED'
    DHSCANNER_PARSER = 'DHSCANNER_PARSER'
    CODEGEN = 'CODEGEN'
    KBGEN = 'KBGEN'
    QUERYENGINE = 'QUERYENGINE'
    RESULTS = 'RESULTS'

class Base(DeclarativeBase):
    pass

@dataclasses.dataclass(kw_only=True)
class LogMessage(Base):

    __tablename__ = 'logs'

    file_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    context: Mapped[Context] = mapped_column(sqlalchemy.Enum(Context), nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)
    duration: Mapped[timedelta] = mapped_column(sqlalchemy .Interval, nullable=False)
