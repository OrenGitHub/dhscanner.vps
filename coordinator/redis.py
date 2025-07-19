import json
import redis
import typing
import dataclasses

from datetime import timedelta

from coordinator import interface
from common.language import Language
from logger.models import Context, LogMessage

REDIS_HOST: typing.Final[str] = 'mq'
REDIS_PORT: typing.Final[int] = 6379

@dataclasses.dataclass(frozen=True)
class RedisCoordinator(interface.Coordinator):

    host: str = dataclasses.field(default=REDIS_HOST, init=False)
    port: int = dataclasses.field(default=REDIS_PORT, init=False)

    redis_client: redis.Redis = dataclasses.field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'redis_client', redis.Redis(
            host=self.host,
            port=self.port
        ))

    @typing.override
    def get_status(self, job_id: str) -> typing.Optional[interface.Status]:
        if raw_bytes := self.get_status_bytes(job_id):
            if raw_str := self.get_status_string(raw_bytes):
                if json_content := self.get_status_json(raw_str):
                    if 'status' in json_content:
                        value = json_content['status']
                        return interface.Status.from_raw_string(value)
        return None

    @typing.override
    def set_status(self, job_id: str, status: interface.Status) -> None:
        status_as_dict = {'status': f'{status.value}'}
        status_str = json.dumps(status_as_dict)
        status_bytes = status_str.encode('utf-8')
        self.redis_client.set(job_id, status_bytes)

    @typing.override
    async def get_jobs_waiting_for(self, desired_status: interface.Status) -> list[str]:

        try:
            keys = self.redis_client.keys('*')
        except redis.exceptions.RedisError:
            await self.logger.warning(
                LogMessage(
                    file_unique_id='*',
                    job_id='*',
                    context=Context.COORDINATOR_NOT_RESPONDING,
                    original_filename='*',
                    language=Language.UNKNOWN,
                    duration=timedelta(0)
                )
            )
            return []

        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if job_status := self.get_status(job_id):
                if job_status == desired_status:
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
