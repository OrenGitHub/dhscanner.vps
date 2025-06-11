import os
import fastapi

# every client must have an approved bearer token to access
EXPECTED_TOKEN = os.getenv('APPROVED_BEARER_TOKEN_0', '')

def check(authorization: str = fastapi.Header(..., alias='Authorization')) -> bool:

    if not authorization.startswith('Bearer '):
        raise fastapi.HTTPException(
            status_code=401,
            detail='Invalid authorization header'
        )

    token = authorization[len('Bearer '):]
    if token != EXPECTED_TOKEN:
        raise fastapi.HTTPException(
            status_code=403,
            detail="Invalid Bearer token"
        )

    return True