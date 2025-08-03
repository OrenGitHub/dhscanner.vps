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

    language = Language.from_filename(filename)
    if language is None:
        language = Language.UNKNOWN

    await logger.info(
        LogMessage(
            file_unique_id='not_allocated_yet',
            job_id=job_id,
            context=Context.UPLOADED_FILE_RECEIVED,
            original_filename=filename,
            language=language,
            duration=timedelta(0)
        )
    )

    gomod = request.headers.get("X-Module-Name-Resolver-Go.mod")

    content = await get_actual_file_content(request)
    await storage.save_file(content, filename, job_id, gomod)
    return {'status': 'ok', 'original_upload_filename': filename}
