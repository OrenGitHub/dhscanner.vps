import typing
import fastapi

from datetime import datetime

import authentication
from coordinator.coordinator import Coordinator

API_ANALYZE_JOB_ID_DESCRIPTION: typing.Final[str] = """
launch multi-step static code analysis
"""

async def run(
    coordinator: Coordinator,
    job_id: str = fastapi.Query(..., description=API_ANALYZE_JOB_ID_DESCRIPTION),
    _=fastapi.Depends(authentication.check)
) -> dict:

    now = datetime.now()
    analysis_started_status = coordinator.AnalysisStarted(now)
    coordinator.set_status(job_id, analysis_started_status)
    return analysis_started(job_id)

def analysis_started(job_id: str) -> dict:
    return {'status': 'ok', 'started_analyzing_job_id': job_id}