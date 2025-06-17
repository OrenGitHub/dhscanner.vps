from __future__ import annotations

import http
import typing
import aiohttp
import asyncio
import dataclasses

from logger.models import Level, LogMessage

MAX_RETRIES: typing.Final[int] = 3
RETRY_DELAY: typing.Final[float] = 0.5
LOGGER_URL:typing.Final[str] = 'http://logger:8000/log'

class Logger:

    @staticmethod
    async def send_attempt(message: LogMessage, level: Level):
        url = f'{LOGGER_URL}/{level.value}'
        data = dataclasses.asdict(message)
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
