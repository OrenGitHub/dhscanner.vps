from coordinator.interface import Coordinator
from coordinator.redis import RedisCoordinator


def get_current_coordinator_between_workers() -> Coordinator:
    return RedisCoordinator()
