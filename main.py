import os
import sys
import typing
import logging
import fastapi

import storage

from redis_coordinator import RedisCoordinator

app = fastapi.FastAPI()

# every client must have an approved bearer token to access
EXPECTED_TOKEN = os.getenv('APPROVED_BEARER_TOKEN_0', '')

# every client must have an approved url to access
# (one url per client, which is also rate limited)
NUM_APPROVED_URLS = os.getenv('NUM_APPROVED_URLS', '1')
APPROVED_URLS = [os.getenv(f'APPROVED_URL_{i}', 'scan') for i in range(int(NUM_APPROVED_URLS))]

limiter = slowapi.Limiter(key_func=lambda request: request.client.host)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s]: %(message)s",
    datefmt="%d/%m/%Y ( %H:%M:%S )",
    stream=sys.stdout
)

x = os.getenv('APPROVED_URL_0', '< undefined >')
logging.info(f'Approved url 0 = {x}')

# generate as many request handlers as needed
# each request handler listens to one approved url
# pylint: disable=cell-var-from-loop,redefined-outer-name
def create_handlers(approved_url: str):

    @app.post(f'api/{approved_url}/upload')
    @limiter.limit('1000/second')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await upload(request, authorization)

    @app.post(f'api/{approved_url}/analyze')
    @limiter.limit('100/minute')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await analyze(request, authorization)

    @app.post(f'api/{approved_url}/status')
    @limiter.limit('100/minute')
    async def _(request: fastapi.Request, authorization: str = fastapi.Header(...)):
        return await status(request, authorization)

for approved_url in APPROVED_URLS:
    create_handlers(approved_url)


API_UPLOAD_JOB_ID_DESCRIPTION: typing.Final[str] = """
every uploaded file belongs to a job(id)
"""

API_UPLOAD_FILENAME_DESCRIPTION: typing.Final[str] = """
relative filename with respect to the source directory root
"""

API_ANALYZE_JOB_ID_DESCRIPTION: typing.Final[str] = """
launch multi-step static code analysis
"""

def authentication_check(authorization: str = fastapi.Header(..., alias='Authorization')) -> bool:

    if not authorization.startswith('Bearer '):
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid authorization header'
        )

    token = authorization[len('Bearer '):]
    if token != EXPECTED_TOKEN:
        raise fastapi.HTTPException(
            status_code=403,
            detail="Invalid Bearer token"
        )

    return True

def content_type_check(content_type: str = fastapi.Header(..., alias='Content-Type')) -> bool:

    if content_type != "application/octet-stream":
        raise fastapi.HTTPException(
            status_code=400,
            detail="Invalid content type"
        )

    return True

# === api functions

async def upload(
    request: fastapi.Request,
    job_id: str = fastapi.Query(..., description=API_UPLOAD_JOB_ID_DESCRIPTION),
    filename: str = fastapi.Header(..., alias="X-Path", description=API_UPLOAD_FILENAME_DESCRIPTION),
    _1=fastapi.Depends(authentication_check),
    _2=fastapi.Depends(content_type_check)
) -> dict:

    content = get_actual_file_content(request)
    storage.store_file(content, filename, job_id)
    return upload_succeeded(filename)

coordinator = RedisCoordinator()

async def status(
    job_id: str = fastapi.Query(..., description=API_ANALYZE_JOB_ID_DESCRIPTION),
    _=fastapi.Depends(authentication_check)
) -> dict:

    return coordinator.get_status(job_id)

async def analyze(
    job_id: str = fastapi.Query(..., description=API_ANALYZE_JOB_ID_DESCRIPTION),
    _=fastapi.Depends(authentication_check)
) -> dict:

    signal_start_analysis(job_id)
    return started_analysis(job_id)

async def get_actual_file_content(request: fastapi.Request) -> typing.AsyncIterator[bytes]:
    return request.stream()

def upload_succeeded(filename: str) -> dict:
    return {'status': 'ok', 'original_upload_filename': filename}