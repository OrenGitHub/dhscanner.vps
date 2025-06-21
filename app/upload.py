import typing
import fastapi

from datetime import timedelta

from logger.client import Logger
from common.language import Language
from storage.interface import Storage
from logger.models import Context, LogMessage

async def get_actual_file_content(request: fastapi.Request) -> typing.AsyncIterator[bytes]:
    return request.stream()

async def run(
    request: fastapi.Request,
    storage: Storage,
    job_id: str,
    filename: str,
    logger: Logger
) -> dict:

    await logger.info(
        LogMessage(
            file_unique_id=filename,
            job_id=job_id,
            context=Context.UPLOAD_FILE,
            original_filename=filename,
            language=Language.UNKNOWN,
            duration=timedelta(0)
        )
    )

    print('MOMOMOMO 777779', flush=True)

    content = await get_actual_file_content(request)
    await storage.save_file(content, filename, job_id)
    return upload_succeeded(filename)

def upload_succeeded(filename: str) -> dict:
    return {'status': 'ok', 'original_upload_filename': filename}
