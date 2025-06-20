import fastapi
import contextlib

from logger import db
from logger import models

@contextlib.asynccontextmanager
async def lifespan(_: fastapi.FastAPI):
    models.Base.metadata.create_all(bind=db.engine)
    yield

app = fastapi.FastAPI(lifespan=lifespan)

@app.post("/log")
def log(serialized_msg: dict) -> fastapi.Response:
    msg = models.LogMessage.fromjson(serialized_msg)
    if msg is None:
        return fastapi.responses.JSONResponse(
            status_code=422,
            content={'detail': 'invalid LogMessage received'}
        )

    with db.SessionLocal() as session:
        session.add(msg)
        session.commit()

    return fastapi.Response(status_code=200)
