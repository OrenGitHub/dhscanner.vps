import os
import sys
import logging
import fastapi
import slowapi

import upload
import status
import analyze

from storage.interface import Storage
from coordinator.interface import Coordinator
from coordinator.redis import RedisCoordinator

app = fastapi.FastAPI()

# pylint: disable=cell-var-from-loop,redefined-outer-name
def create_handlers(approved_url: str, coordinator: Coordinator, storage: Storage):

    limiter = slowapi.Limiter(key_func=lambda request: request.client.host)

    @app.post(f'api/{approved_url}/upload')
    @limiter.limit('1000/second')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await upload.run(storage, request, authorization)

    @app.post(f'api/{approved_url}/analyze')
    @limiter.limit('100/minute')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await analyze.run(request, authorization, coordinator)

    @app.post(f'api/{approved_url}/status')
    @limiter.limit('100/minute')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await status.run(request, authorization, coordinator)

# every client must have an approved url to access
# (one url per client, which is also rate limited)
def define_endpoints(coordinator: Coordinator) -> None:
    num_approved_urls = os.getenv('NUM_APPROVED_URLS', '1')
    approved_urls = [os.getenv(f'APPROVED_URL_{i}', 'scan') for i in range(int(num_approved_urls))]
    for approved_url in approved_urls:
        create_handlers(approved_url, coordinator)

def configure_logger() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s]: %(message)s",
        datefmt="%d/%m/%Y ( %H:%M:%S )",
        stream=sys.stdout
    )

def init(coordinator: Coordinator) -> None:
    configure_logger()
    define_endpoints(coordinator)

init(RedisCoordinator())
