import json
import redis
import typing
import dataclasses

from datetime import datetime

from . import interface

REDIS_HOST: typing.Final[str] = 'redis'
REDIS_PORT: typing.Final[int] = 6379

@dataclasses.dataclass(frozen=True)
class RedisCoordinator(interface.Coordinator):

    host: typing.Final[str] = REDIS_HOST
    port: typing.Final[int] = REDIS_PORT
 
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
        status_as_dict = dataclasses.asdict(status)
        status_str = json.dumps(status_as_dict)
        status_bytes = status_str.encode('utf-8')
        self.redis_client.set(job_id, status_bytes)

    @typing.override
    def get_jobs_waiting_for_step_0_native_parsing(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.wait_for_step_0_native_parsing():
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def get_jobs_waiting_for_step_1_dhscanner_parsing(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.wait_for_step_1_dhscanner_parsing():
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def get_jobs_waiting_for_step_2_code_generation(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.wait_for_step_2_code_generation():
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def get_jobs_waiting_for_step_3_knwoledge_base_generation(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.wait_for_step_3_knowledge_base_generation():
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def get_jobs_waiting_for_step_4_query_engine(self) -> list[str]:
        keys = self.redis_client.keys('*')
        job_ids = []
        for key in keys:
            job_id = key.decode('utf-8')
            if status := self.get_status(job_id):
                if status.wait_for_step_4_query_engine():
                    job_ids.append(job_id)

        return job_ids

    @typing.override
    def mark_jobs_that_finished_step_0_and_now_wait_for_step_1(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            now = datetime.now()
            native_parsing_finished = interface.NativeParsingFinished(now)
            self.set_status(job_id, native_parsing_finished)

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
