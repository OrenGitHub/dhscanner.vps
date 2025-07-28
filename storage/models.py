import sqlalchemy

from sqlalchemy.orm import DeclarativeBase # type: ignore[attr-defined]
from sqlalchemy.orm import Mapped # type: ignore[attr-defined]
from sqlalchemy.orm import mapped_column # type: ignore[attr-defined]

from common.language import Language

# pylint: disable=too-few-public-methods
class Base(DeclarativeBase):
    pass

# pylint: disable=too-few-public-methods
class FileMetadata(Base):

    __tablename__ = 'files'

    file_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

# pylint: disable=too-few-public-methods
class NativeAstMetadata(Base):
    '''
    Initialize with keywords

    ---

    - `native_ast_unique_id`: `str`
    - `job_id`: `str`
    - `original_filename`: `str`
    - `language`: `Language`
    '''

    __tablename__ = 'native_asts'

    native_ast_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

# pylint: disable=too-few-public-methods
class DhscannerAstMetadata(Base):
    '''
    Initialize with keywords

    ---

    - `dhscanner_ast_unique_id`: `str`
    - `job_id`: `str`
    - `original_filename`: `str`
    - `language`: `Language`
    '''

    __tablename__ = 'dhscanner_asts'

    dhscanner_ast_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

# pylint: disable=too-few-public-methods
class CallablesMetadata(Base):
    '''
    Initialize with keywords

    ---

    - `callable_unique_id`: `str`
    - `num_callables`: `int`
    - `job_id`: `str`
    - `original_filename`: `str`
    - `language`: `Language`
    '''

    __tablename__ = 'callables'

    callable_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    num_callables: Mapped[int] = mapped_column(sqlalchemy.Integer, nullable=False)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

# pylint: disable=too-few-public-methods
class FactsMetadata(Base):
    '''
    Initialize with keywords

    ---

    - `facts_unique_id`: `str`
    - `job_id`: `str`
    - `original_filename`: `str`
    - `language`: `Language`
    '''

    __tablename__ = 'knowledge_base_facts'

    facts_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

# pylint: disable=too-few-public-methods
class ResultsMetadata(Base):
    '''
    Initialize with keywords

    ---

    - `results`: `str` ( primary )
    - `job_id`: `str`
    '''
    __tablename__ = 'results'

    results: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
