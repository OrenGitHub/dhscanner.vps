import contextlib
import fastapi

from . import db
from . import models

app = fastapi.FastAPI()

@contextlib.asynccontextmanager
async def lifespan(_: fastapi.FastAPI):
    async with db.engine.begin() as connection:
        await connection.run_sync(models.Base.metadata.create_all)
    yield

@app.post("/log")
def log(msg: models.LogMessage) -> fastapi.Response:
    with db.SessionLocal() as session:
        session.add(msg)
        session.commit()

    return fastapi.Response(status_code=200)
