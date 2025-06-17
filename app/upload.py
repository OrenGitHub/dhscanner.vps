import typing
import fastapi

from storage.interface import Storage

async def get_actual_file_content(request: fastapi.Request) -> typing.AsyncIterator[bytes]:
    return request.stream()

async def run(request: fastapi.Request, storage: Storage, job_id: str, filename: str) -> dict:
    content = await get_actual_file_content(request)
    await storage.save_file(content, filename, job_id)
    return upload_succeeded(filename)

def upload_succeeded(filename: str) -> dict:
    return {'status': 'ok', 'original_upload_filename': filename}
