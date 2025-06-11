from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import os

DB_USER = os.getenv('POSTGRES_USER', 'user')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'password')

DB_HOST = 'logger'
DB_NAME = 'logs'
DB_KIND = 'postgresql+psycopg2'

DATABASE_URL = f'{DB_KIND}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(bind=engine)