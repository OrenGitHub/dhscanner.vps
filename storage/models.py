from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import sqlalchemy

from common.language import Language

class Base(DeclarativeBase):
    pass

class FileMetadata(Base):

    __tablename__ = 'files'

    file_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.SQLEnum(Language), nullable=False)

class AstMetadata(Base):

    __tablename__ = 'asts'

    ast_unique_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    job_id: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    original_filename: Mapped[str] = mapped_column(sqlalchemy.String, nullable=False)
    language: Mapped[Language] = mapped_column(sqlalchemy.SQLEnum(Language), nullable=False)
