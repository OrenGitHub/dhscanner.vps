from logger.client import Logger
from workers.queryengine import main
from coordinator.interface import Status
from storage.current import get_current_storage_method
from coordinator.current import get_coordinator_between_workers

if __name__ == '__main__':
    logger = Logger()
    worker = main.Queryengine(
        logger,
        get_current_storage_method(logger),
        get_coordinator_between_workers(logger),
        Status.WaitingForQueryengine
    )
    worker.check_in()
