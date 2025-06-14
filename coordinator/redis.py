import json
import redis
import typing
import dataclasses

from . import interface

REDIS_HOST: typing.Final[str] = 'redis'
REDIS_PORT: typing.Final[int] = 6379

@dataclasses.dataclass(frozen=True)
class RedisCoordinator(interface.Coordinator):

    host: str = dataclasses.field(default=REDIS_HOST, init=False)
    port: int = dataclasses.field(default=REDIS_PORT, init=False)
 
    redis_client: redis.Redis = dataclasses.field(init=False)

    def __post_init__(self):
        self.redis_client = redis.Redis(
            host=self.host,
            port=self.port
        )

    @typing.override
    def get_status(self, job_id: str) -> typing.Optional[interface.Status]:
        if raw_bytes := self.get_status_bytes(job_id):
            if raw_str := self.get_status_string(raw_bytes):
                if json_content := self.get_status_json(raw_str):
                    if status := interface.Status.from_dict(json_content):
                        return status
        return None

    @typing.override
    def set_status(self, job_id: str, status: interface.Status) -> None:
        status_as_dict = {'status': f'{status.value}'}
        status_str = json.dumps(status_as_dict)
        status_bytes = status_str.encode('utf-8')
        self.redis_client.set(job_id, status_bytes)

    @typing.override
    def get_jobs_waiting_for(self, desired_status: interface.Status) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if job_status := self.get_status(job_id):
                if job_status.is_the_same_as(desired_status):
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def mark_jobs_finished(self, job_ids: list[str]) -> None:
        self.redis_client.delete(*job_ids)

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
