import json
import typing
import fastapi

from datetime import timedelta

from logger.client import Logger
from common.language import Language
from storage.interface import Storage
from logger.models import Context, LogMessage

async def get_actual_file_content(request: fastapi.Request) -> typing.AsyncIterator[bytes]:
    return request.stream()

def is_valid_path_mappings(candidate: typing.Any) -> bool:
    if not isinstance(candidate, list):
        return False

    for item in candidate:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {'from', 'to'}:
            return False
        if not isinstance(item['from'], str) or not isinstance(item['to'], str):
            return False

    return True

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
    github_url = request.headers.get("X-GitHub-URL")
    raw_path_mappings = request.headers.get("X-Path-Mappings")
    path_mappings: typing.Optional[list[dict[str, str]]] = None
    if raw_path_mappings is not None:
        try:
            candidate = json.loads(raw_path_mappings)
            if is_valid_path_mappings(candidate):
                path_mappings = candidate
        except json.JSONDecodeError:
            path_mappings = None

    content = await get_actual_file_content(request)
    await storage.save_file(content, filename, job_id, gomod, github_url, path_mappings)
    return {'status': 'ok', 'original_upload_filename': filename}
