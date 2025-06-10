import sqlalchemy
from sqlalchemy.orm import sessionmaker

engine = sqlalchemy.create_engine(
    'sqlite:///dhscanner.db',
    connect_args={'check_same_thread': False}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)