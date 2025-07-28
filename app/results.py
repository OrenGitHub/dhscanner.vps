import http

from fastapi.responses import JSONResponse

from storage.interface import Storage
from coordinator.interface import Coordinator, Status

async def run(coordinator: Coordinator, storage: Storage, job_id: str) -> dict | JSONResponse:

    if coordinator.get_status(job_id) != Status.Finished:
        return JSONResponse(
            status_code=http.HTTPStatus.ACCEPTED,
            content={'detail': 'results are not ready yet ... stay tuned !'}
        )

    return await storage.load_output(job_id)
