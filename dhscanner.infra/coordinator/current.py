import time
import redis
import typing

from logger.client import Logger
from coordinator.interface import Coordinator
from coordinator.redis import RedisCoordinator

MAX_NUM_ATTEMPS_CONNECTING_TO_COORDINATOR: typing.Final[int] = 10

def get_coordinator_between_workers(logger: Logger) -> typing.Optional[Coordinator]:
    for _ in range(MAX_NUM_ATTEMPS_CONNECTING_TO_COORDINATOR):
        try:
            coordinator = RedisCoordinator(logger)
            coordinator.redis_client.ping()
            return coordinator
        except redis.exceptions.ConnectionError:
            time.sleep(1)

    return None
