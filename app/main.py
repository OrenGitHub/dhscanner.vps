import os
import sys
import typing
import fastapi
import slowapi
import logging
import secrets
import contextlib

from storage import db, models
from logger.client import Logger
from storage.current import get_current_storage_method

from app import upload
from app import status
from app import analyze
from app import authentication

from storage.interface import Storage
from coordinator.interface import Coordinator
from coordinator.redis import RedisCoordinator

@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    models.Base.metadata.create_all(bind=db.engine)
    yield

app = fastapi.FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan
)

API_UPLOAD_JOB_ID_DESCRIPTION: typing.Final[str] = """
every uploaded file belongs to a job(id)
"""

API_UPLOAD_FILENAME_DESCRIPTION: typing.Final[str] = """
relative filename with respect to the source directory root
"""

API_ANALYZE_JOB_ID_DESCRIPTION: typing.Final[str] = """
launch multi-step static code analysis
"""

API_STATUS_JOB_ID_DESCRIPTION: typing.Final[str] = """
launch multi-step static code analysis
"""

# pylint: disable=cell-var-from-loop,redefined-outer-name
def create_handlers(
    approved_url: str,
    coordinator: Coordinator,
    storage: Storage,
    logger: Logger
):

    limiter = slowapi.Limiter(key_func=lambda request: request.client.host)

    @app.get(f'/api/{approved_url}/getjobid')
    @limiter.limit('100/minute')
    async def _(
        request: fastapi.Request,
        _=fastapi.Depends(authentication.check)
    ):
        return {'job_id': secrets.token_hex(16)}

    @app.post(f'/api/{approved_url}/upload')
    @limiter.limit('1000/second')
    async def _(
        request: fastapi.Request,
        job_id: str = fastapi.Query(..., description=API_UPLOAD_JOB_ID_DESCRIPTION),
        filename: str = fastapi.Header(..., alias='X-Path', description=API_UPLOAD_FILENAME_DESCRIPTION),
        _1=fastapi.Depends(authentication.check),
        _2=fastapi.Depends(content_type_check),
    ):
        return await upload.run(request, storage, job_id, filename, logger)

    @app.post(f'/api/{approved_url}/analyze')
    @limiter.limit('100/minute')
    async def _(
        request: fastapi.Request,
        job_id: str = fastapi.Query(..., description=API_ANALYZE_JOB_ID_DESCRIPTION),
        _=fastapi.Depends(authentication.check)
    ):
        return await analyze.run(coordinator, job_id)

    @app.post(f'/api/{approved_url}/status')
    @limiter.limit('100/minute')
    async def _(
        request: fastapi.Request,
        job_id: str = fastapi.Query(..., description=API_STATUS_JOB_ID_DESCRIPTION),
        _=fastapi.Depends(authentication.check)
    ):
        return await status.run(coordinator, job_id)

# every client must have an approved url to access
# (one url per client, which is also rate limited)
def define_endpoints(storage: Storage, coordinator: Coordinator, logger: Logger) -> None:
    num_approved_urls = os.getenv('NUM_APPROVED_URLS', '1')
    approved_urls = [os.getenv(f'APPROVED_URL_{i}', 'scan') for i in range(int(num_approved_urls))]
    for approved_url in approved_urls:
        create_handlers(approved_url, coordinator, storage, logger)

def configure_logger() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s]: %(message)s",
        datefmt="%d/%m/%Y ( %H:%M:%S )",
        stream=sys.stdout
    )

def content_type_check(content_type: str = fastapi.Header(..., alias='Content-Type')) -> bool:

    if content_type != "application/octet-stream":
        raise fastapi.HTTPException(
            status_code=400,
            detail="Invalid content type"
        )

    return True

def init(coordinator: Coordinator) -> None:
    logger = Logger()
    storage = get_current_storage_method(logger)
    define_endpoints(storage, coordinator, logger)

init(RedisCoordinator(Logger()))
