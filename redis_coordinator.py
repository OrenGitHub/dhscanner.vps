import json
import redis
import typing
import dataclasses

from coordinator import (
    Coordinator,
    Status
)

REDIS_HOST: typing.Final[str] = 'redis'
REDIS_PORT: typing.Final[int] = 6379

@dataclasses.dataclass(frozen=True)
class RedisCoordinator(Coordinator):

    host: typing.Final[str] = REDIS_HOST
    port: typing.Final[int] = REDIS_PORT
 
    redis_client: redis.Redis = dataclasses.field(init=False)

    def __post_init__(self):
        self.redis_client = redis.Redis(
            host=self.host,
            port=self.port
        )

    @typing.override
    def get_status(self, job_id: str) -> typing.Optional[Status]:
        if raw_bytes := self.get_status_bytes(job_id):
            if raw_str := self.get_status_string(raw_bytes):
                if json_content := self.get_status_json(raw_str):
                    if status := Status.from_dict(json_content):
                        return status
        return None

    @typing.override
    def set_status(self, job_id: str, status: Status) -> None:
        status_as_dict = dataclasses.asdict(status)
        status_str = json.dumps(status_as_dict)
        status_bytes = status_str.encode('utf-8')
        self.redis_client.set(job_id, status_bytes)

    def get_jobs_to_analyze(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.start_analyzing():
                    job_ids.append(job_id)

        return job_ids

    def get_status_bytes(self, job_id: str) -> typing.Optional[bytes]:
        return self.redis_client.get(job_id)

    def get_status_string(self, raw_bytes: bytes) -> typing.Optional[str]:
        try:
            return raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return None

    def get_status_json(self, raw_string: str) -> typing.Optional[dict]:
        try:
            return json.loads(raw_string)
        except json.JSONDecodeError:
            return None
