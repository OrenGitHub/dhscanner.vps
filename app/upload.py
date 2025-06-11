import typing
import fastapi

import authentication
from coordinator.coordinator import Coordinator

API_UPLOAD_JOB_ID_DESCRIPTION: typing.Final[str] = """
every uploaded file belongs to a job(id)
"""

API_UPLOAD_FILENAME_DESCRIPTION: typing.Final[str] = """
relative filename with respect to the source directory root
"""

def content_type_check(content_type: str = fastapi.Header(..., alias='Content-Type')) -> bool:

    if content_type != "application/octet-stream":
        raise fastapi.HTTPException(
            status_code=400,
            detail="Invalid content type"
        )

    return True

async def get_actual_file_content(request: fastapi.Request) -> typing.AsyncIterator[bytes]:
    return request.stream()

async def run(
    coordinator: Coordinator,
    request: fastapi.Request,
    job_id: str = fastapi.Query(..., description=API_UPLOAD_JOB_ID_DESCRIPTION),
    filename: str = fastapi.Header(..., alias="X-Path", description=API_UPLOAD_FILENAME_DESCRIPTION),
    _1=fastapi.Depends(authentication.check),
    _2=fastapi.Depends(content_type_check)
) -> dict:

    content = await get_actual_file_content(request)
    await storage.store_file(content, filename, job_id)
    return upload_succeeded(filename)

def upload_succeeded(filename: str) -> dict:
    return {'status': 'ok', 'original_upload_filename': filename}
