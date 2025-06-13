from . import main
from logger.client import Logger

from storage.current import get_current_storage_method
from coordinator.current import get_current_coordinator_between_workers

if __name__ == '__main__':
    worker = main.Codegen(
        Logger(),
        get_current_storage_method(),
        get_current_coordinator_between_workers()
    )
    worker.check_in()