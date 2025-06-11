import typing
import fastapi
import dataclasses

from app import authentication
from coordinator.interface import Coordinator

API_ANALYZE_JOB_ID_DESCRIPTION: typing.Final[str] = """
launch multi-step static code analysis
"""

async def run(
    coordinator: Coordinator,
    job_id: str = fastapi.Query(..., description=API_ANALYZE_JOB_ID_DESCRIPTION),
    _=fastapi.Depends(authentication.check)
) -> dict:

    if status := coordinator.get_status(job_id):
        return dataclasses.asdict(status)
    
    return {'status': f'fatal error processing job(id): {job_id}'}
