import time
import typing
import sqlalchemy

from storage import db
from logger.client import Logger
from storage.interface import Storage
from storage.local import LocalStorage

MAX_NUM_ATTEMPS_CONNECTING_TO_STORAGE_MANAGER: typing.Final[int] = 10

def get_current_storage_method(logger: Logger) -> Storage:

    for _ in range(MAX_NUM_ATTEMPS_CONNECTING_TO_STORAGE_MANAGER):
        try:
            with db.SessionLocal() as session:
                session.execute(sqlalchemy.text('PRAGMA table_info(files);'))
            return LocalStorage(logger)
        except sqlalchemy.exc.OperationalError:
            time.sleep(1)

    return None
