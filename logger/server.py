import typing
import asyncio
import fastapi
import psycopg2
import contextlib

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
