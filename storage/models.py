import sqlalchemy

from sqlalchemy.orm import DeclarativeBase # type: ignore[attr-defined]
from sqlalchemy.orm import Mapped # type: ignore[attr-defined]
from sqlalchemy.orm import mapped_column # type: ignore[attr-defined]

from common.language import Language

class Base(DeclarativeBase):
    pass

class FileMetadata(Base):

    __tablename__ = 'files'

    file_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

class NativeAstMetadata(Base):

    __tablename__ = 'native_asts'

    native_ast_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

class DhscannerAstMetadata(Base):

    __tablename__ = 'dhscanner_asts'

    dhscanner_ast_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

class CallablesMetadata(Base):

    __tablename__ = 'callables'

    callable_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    num_callables: Mapped[int] = mapped_column(sqlalchemy.Integer, nullable=False)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)

class KbgenFactsMetadata(Base):

    __tablename__ = 'knowledge_base_facts'

    knowledge_base_facts_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    num_callables: Mapped[int] = mapped_column(sqlalchemy.Integer, nullable=False)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.Enum(Language), nullable=False)
