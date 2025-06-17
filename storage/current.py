from logger.client import Logger
from storage.interface import Storage
from storage.local import LocalStorage

def get_current_storage_method(logger: Logger) -> Storage:
    return LocalStorage(logger)
