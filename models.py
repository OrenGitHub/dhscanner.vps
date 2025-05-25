import sqlalchemy

from language import Language

metadata = sqlalchemy.MetaData()

FILES = sqlalchemy.Table(
    'FILES',
    metadata,
    sqlalchemy.Column('file_unique_id', sqlalchemy.String, primary_key=True),
    sqlalchemy.Column('job_id', sqlalchemy.String, nullable=False),
    sqlalchemy.Column('original_filename', sqlalchemy.String, nullable=False),
    sqlalchemy.Column('language', sqlalchemy.SQLEnum(Language), nullable=False),
)