import dataclasses
import enum

from datetime import timedelta

import sqlalchemy

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column
)

from common.language import Language

class Level(str, enum.Enum):
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'

class Context(str, enum.Enum):
    UPLOAD_FILE = 'UPLOAD_FILE'
    NATIVE_PARSER = 'NATIVE_PARSER'
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
    context: Mapped[Context] = mapped_column(sqlalchemy.SQLEnum(Context), nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.SQLEnum(Language), nullable=False)
    duration: Mapped[timedelta] = mapped_column(sqlalchemy .Interval, nullable=False)
