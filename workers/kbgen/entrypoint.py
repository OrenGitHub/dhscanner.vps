from kbgen import main
from logger.client import Logger
from coordinator.interface import Status
from storage.current import get_current_storage_method
from coordinator.current import get_current_coordinator_between_workers

if __name__ == '__main__':
    logger = Logger()
    worker = main.Kbgen(
        logger,
        get_current_storage_method(logger),
        get_current_coordinator_between_workers(),
        Status.WaitingForKbgen
    )
    worker.check_in()
