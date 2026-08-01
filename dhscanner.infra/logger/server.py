import typing
import asyncio
import fastapi
import psycopg2
import contextlib
import sqlalchemy

from sqlalchemy.engine import CursorResult

from logger import db
from logger import models

MAX_NUM_ATTEMPTS_CONNECTING_TO_LOGGER: typing.Final[int] = 10
NUM_SECONDS_TO_WAIT_BETWEEN_ATTEMPTS: typing.Final[int] = 1

async def logger_to_be_ready():
    for _ in range(MAX_NUM_ATTEMPTS_CONNECTING_TO_LOGGER):
        try:
            conn = psycopg2.connect(
                host=db.DB_HOST,
                user=db.DB_USER,
                password=db.DB_PASSWORD,
                dbname=db.DB_NAME
            )
            conn.close()
            return
        except psycopg2.OperationalError:
            await asyncio.sleep(
                NUM_SECONDS_TO_WAIT_BETWEEN_ATTEMPTS
            )

    raise fastapi.HTTPException(
        status_code=fastapi.status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="logger service is unreachable"
    )

@contextlib.asynccontextmanager
async def lifespan(_: fastapi.FastAPI):
    await logger_to_be_ready()
    models.Base.metadata.create_all(bind=db.engine)
    yield

app = fastapi.FastAPI(lifespan=lifespan)

@app.post("/log")
def log(serialized_msg: dict) -> fastapi.Response:

    msg = models.LogMessage.fromjson(serialized_msg)
    if msg is None:
        return fastapi.responses.JSONResponse(
            status_code=fastapi.status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={'detail': 'invalid LogMessage received'}
        )

    with db.SessionLocal() as session:
        session.add(msg)
        session.commit()

    return fastapi.Response(status_code=200)

@app.delete("/log/{job_id}")
def delete_logs_for_job(job_id: str) -> dict:
    # Operator-only path: paired with the app-tier `--clear-job-id` flow
    # so the audit trail does not outlive the runtime state it describes
    # (keeping orphaned log rows around would defeat the operator's
    # mental model of "the job is gone").
    with db.SessionLocal() as session:
        # Session.execute() is typed as returning the base Result[Any],
        # but for DML statements (DELETE/UPDATE/INSERT) the actual
        # runtime object is a CursorResult, which is where `rowcount`
        # lives. Cast once so the attribute access is statically valid.
        result = typing.cast(CursorResult, session.execute(
            sqlalchemy.delete(models.LogMessage).where(
                models.LogMessage.job_id == job_id
            )
        ))
        session.commit()
        return {'deleted': result.rowcount or 0}

@app.delete("/log")
def delete_all_logs() -> dict:
    # Bulk variant for `--clear-all`. Uses a plain DELETE (not TRUNCATE)
    # so it stays inside SQLAlchemy's ORM-friendly path and respects
    # whatever connection-level isolation the surrounding session has.
    with db.SessionLocal() as session:
        # Same Result -> CursorResult cast as in delete_logs_for_job;
        # see that function for why rowcount needs the narrower type.
        result = typing.cast(CursorResult, session.execute(sqlalchemy.delete(models.LogMessage)))
        session.commit()
        return {'deleted': result.rowcount or 0}
