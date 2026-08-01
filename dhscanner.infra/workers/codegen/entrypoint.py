from logger.client import Logger
from workers.codegen import main
from coordinator.interface import Status
from storage.current import get_current_storage_method
from coordinator.current import get_coordinator_between_workers

if __name__ == '__main__':
    logger = Logger()
    if storage := get_current_storage_method(logger):
        if coordinator := get_coordinator_between_workers(logger):
            worker = main.Codegen(
                logger,
                storage,
                coordinator,
                Status.WaitingForCodegen
            )
            worker.check_in()
