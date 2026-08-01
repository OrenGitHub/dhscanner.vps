from __future__ import annotations

import http
import typing
import aiohttp
import asyncio

from logger.models import Level, LogMessage

MAX_RETRIES: typing.Final[int] = 3
RETRY_DELAY: typing.Final[float] = 0.5
LOGGER_URL:typing.Final[str] = 'http://logger_server:8000/log'
LOGGER_BASE_URL: typing.Final[str] = 'http://logger_server:8000'

class Logger:

    @staticmethod
    async def send_attempt(message: LogMessage, _level: Level):
        url = LOGGER_URL
        data = message.tojson()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    return response.status == http.HTTPStatus.OK
        except aiohttp.ClientError:
            return False

    @staticmethod
    async def send(message: LogMessage, level: Level):
        reactive_delay = RETRY_DELAY
        for _ in range(MAX_RETRIES):
            if await Logger.send_attempt(message, level):
                break
            await asyncio.sleep(reactive_delay)
            reactive_delay *= 2

    @staticmethod
    async def error(message: LogMessage):
        await Logger.send(message, Level.ERROR)

    @staticmethod
    async def info(message: LogMessage):
        await Logger.send(message, Level.INFO)

    @staticmethod
    async def warning(message: LogMessage):
        await Logger.send(message, Level.WARNING)

    @staticmethod
    async def debug(message: LogMessage):
        await Logger.send(message, Level.DEBUG)

    @staticmethod
    async def delete_for_job(job_id: str) -> bool:
        # Operator-only: wipe every PG `logs` row that references this
        # job. Surfaces errors as a boolean (mirrors `send_attempt`) so
        # the caller can decide whether to flag a partial wipe to the
        # human without raising across the FastAPI handler boundary.
        url = f'{LOGGER_BASE_URL}/log/{job_id}'
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url) as response:
                    return response.status == http.HTTPStatus.OK
        except aiohttp.ClientError:
            return False

    @staticmethod
    async def delete_all() -> bool:
        # Bulk wipe, paired with `--clear-all` on the CLI side.
        url = f'{LOGGER_BASE_URL}/log'
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url) as response:
                    return response.status == http.HTTPStatus.OK
        except aiohttp.ClientError:
            return False
