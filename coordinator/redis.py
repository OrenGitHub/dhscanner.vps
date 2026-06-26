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
    def get_agent_mode(self, job_id: str) -> bool:
        key = self.get_agent_mode_key(job_id)
        if raw_bytes := self.redis_client.get(key):
            return raw_bytes.decode('utf-8') == 'True'
        return False

    @typing.override
    def set_agent_mode(self, job_id: str, agent_mode: bool) -> None:
        key = self.get_agent_mode_key(job_id)
        self.redis_client.set(key, str(agent_mode))

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

    @typing.override
    async def clear_job(self, job_id: str) -> None:
        # Wipe every Redis trace of one job: the status key, plus the two
        # sidecar keys (agent_mode / kb_location) created lazily during
        # the analyze flow. DEL is idempotent and missing-key tolerant,
        # so this is safe to call repeatedly even when sidecars never
        # came into existence (e.g. a job that died before /analyze).
        try:
            self.redis_client.delete(
                job_id,
                self.get_agent_mode_key(job_id),
                f'{job_id}:kb_location',
            )
        except redis.exceptions.RedisError:
            await self.logger.warning(
                LogMessage(
                    file_unique_id='*',
                    job_id=job_id,
                    context=Context.COORDINATOR_NOT_RESPONDING,
                    original_filename='*',
                    language=Language.UNKNOWN,
                    duration=timedelta(0)
                )
            )

    @typing.override
    async def clear_all_jobs(self) -> int:
        # FLUSHDB-equivalent but scoped to job-shaped keys, so any future
        # tenant of this redis (e.g. caches that grow next to the queue)
        # stays untouched. We discover top-level job ids the same way
        # `list_all_job_ids` does and then delegate per-id deletion to
        # `clear_job` so the sidecar-key rules live in exactly one place.
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
            return 0

        job_ids = [k.decode('utf-8') for k in keys if ':' not in k.decode('utf-8')]
        for job_id in job_ids:
            await self.clear_job(job_id)
        return len(job_ids)

    @typing.override
    async def list_all_job_ids(self) -> list[str]:
        # Redis is the source of truth for "a job exists": every job-id is
        # set as a top-level key whose value is the status JSON. Sidecar
        # state (agent_mode / kb_location) lives under composite keys like
        # `<job_id>:agent_mode`, which we filter out by rejecting anything
        # with a colon so this endpoint only returns the bare job IDs.
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

        job_ids: list[str] = []
        for key in keys:
            decoded = key.decode('utf-8')
            if ':' in decoded:
                continue
            job_ids.append(decoded)

        job_ids.sort()
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

    @typing.override
    def get_kb_location(self, job_id: str) -> typing.Optional[str]:
        if raw_bytes := self.redis_client.get(f'{job_id}:kb_location'):
            return raw_bytes.decode('utf-8')
        return None

    @typing.override
    def set_kb_location(self, job_id: str, kb_location: str) -> None:
        self.redis_client.set(f'{job_id}:kb_location', kb_location)

    def get_agent_mode_key(self, job_id: str) -> str:
        return f'{job_id}:agent_mode'
