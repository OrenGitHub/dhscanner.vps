from storage.interface import Storage
from storage.local import LocalStorage

def get_current_storage_method() -> Storage:
    return LocalStorage()