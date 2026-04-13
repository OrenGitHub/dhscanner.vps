from coordinator.interface import (
    Status,
    Coordinator
)

async def run(coordinator: Coordinator, job_id: str, agent_mode: bool) -> dict:
    status = Status.WaitingForNativeParsing
    coordinator.set_status(job_id, status)
    coordinator.set_agent_mode(job_id, agent_mode)
    return analysis_started(job_id)

def analysis_started(job_id: str) -> dict:
    return {'status': 'ok', 'started_analyzing_job_id': job_id}
