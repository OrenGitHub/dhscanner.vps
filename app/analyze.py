from coordinator.interface import (
    Status,
    Coordinator
)

async def run(coordinator: Coordinator, job_id: str) -> dict:
    status = Status.WaitingForNativeParsing
    coordinator.set_status(job_id, status)
    return analysis_started(job_id)

def analysis_started(job_id: str) -> dict:
    return {'status': 'ok', 'started_analyzing_job_id': job_id}
