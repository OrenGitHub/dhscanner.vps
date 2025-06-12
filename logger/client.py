from __future__ import annotations

import http
import time
import typing
import aiohttp
import asyncio
import dataclasses

from datetime import timedelta

from contextlib import asynccontextmanager

from storage.models import FileMetadata
from logger.models import Context, Level, LogMessage

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
            else:
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

    @asynccontextmanager
    async def time_this_info_msg(self, context: Context, f: FileMetadata):
        start = time.monotonic()
        try:
            yield
        finally:
            delta = time.monotonic() - start
            await self.info(
                LogMessage(
                    file_unique_id=f.file_unique_id,
                    job_id=f.job_id,
                    context=context,
                    original_filename=f.original_filename,
                    language=f.language,
                    duration=timedelta(seconds=delta)
                )
            )

