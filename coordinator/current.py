from logger.client import Logger
from coordinator.interface import Coordinator
from coordinator.redis import RedisCoordinator

def get_current_coordinator_between_workers(logger: Logger) -> Coordinator:
    return RedisCoordinator(logger)
