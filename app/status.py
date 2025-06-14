import dataclasses

from coordinator.interface import Coordinator

async def run(coordinator: Coordinator, job_id: str) -> dict:

    if status := coordinator.get_status(job_id):
        return {'status': f'{status.value}'}
    
    return {'status': f'fatal error processing job(id): {job_id}'}
