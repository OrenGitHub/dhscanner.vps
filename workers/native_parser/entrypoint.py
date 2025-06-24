from logger.client import Logger
from workers.native_parser import main
from coordinator.interface import Status
from storage.current import get_current_storage_method
from coordinator.current import get_coordinator_between_workers

if __name__ == '__main__':
    logger = Logger()
    if coordinator := get_coordinator_between_workers(logger):
        worker = main.NativeParser(
            logger,
            get_current_storage_method(logger),
            coordinator,
            Status.WaitingForNativeParsing
        )
        worker.check_in()
