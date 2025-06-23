from codegen import main
from logger.client import Logger
from coordinator.interface import Status
from storage.current import get_current_storage_method
from coordinator.current import get_coordinator_between_workers

if __name__ == '__main__':
    logger = Logger()
    worker = main.Codegen(
        logger,
        get_current_storage_method(logger),
        get_coordinator_between_workers(logger),
        Status.WaitingForCodegen
    )
    worker.check_in()
