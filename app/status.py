import typing
import fastapi
import dataclasses

from app import authentication
from coordinator.interface import Coordinator

async def run(coordinator: Coordinator, job_id: str) -> dict:

    if status := coordinator.get_status(job_id):
        return dataclasses.asdict(status)
    
    return {'status': f'fatal error processing job(id): {job_id}'}
