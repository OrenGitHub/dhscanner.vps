"""CLI-side console logging configuration.

Owns one thing: the look-and-feel of `cli.py`'s stdout log stream. Kept
in its own module so `cli.py` doesn't have to host the ANSI palette and
the custom formatter, and so a future second CLI-shaped entry point can
get the same look by importing one symbol.

Public surface is intentionally tiny -- `configure()` -- so callers don't
get tempted to reach into internals. Anything underscored here is an
implementation detail and may change.
"""

from __future__ import annotations

import os
import sys
import typing
import logging

# ANSI color codes for the level-name slot. Keep this list short and
# centralized so a future user-facing palette change is a one-line edit.
# Conventions:
#   DEBUG    -> bright cyan ("light blue") -- the visual demotion that
#               makes high-frequency progress noise easy to skim past
#   INFO     -> green        (positive, default-noticed signal)
#   WARNING  -> yellow
#   ERROR    -> red
#   CRITICAL -> bold red
_LEVEL_COLORS: typing.Final[dict[str, str]] = {
    'DEBUG':    '\033[96m',
    'INFO':     '\033[32m',
    'WARNING':  '\033[33m',
    'ERROR':    '\033[31m',
    'CRITICAL': '\033[1;31m',
}
_ANSI_RESET: typing.Final[str] = '\033[0m'

_DEFAULT_FMT: typing.Final[str] = "[%(asctime)s] [%(levelname)s]: %(message)s"
_DEFAULT_DATEFMT: typing.Final[str] = "%d/%m/%Y ( %H:%M:%S )"


class _LevelColorFormatter(logging.Formatter):
    """Wraps `%(levelname)s` in an ANSI color for the duration of one record.

    We mutate `record.levelname` in-place (not the format string) so the
    width of the substituted text isn't disturbed for downstream handlers,
    and we always restore the original in a `finally` so a colorized record
    doesn't leak its escape codes into log files / other handlers.

    Color is suppressed when stdout isn't a TTY (e.g. piped to a file or
    CI capture) or when the `NO_COLOR` env var is set (de-facto cross-tool
    standard). This is computed once at formatter construction so the
    per-record path stays cheap.
    """

    def __init__(self, fmt: str, datefmt: str, use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self._use_color:
            return super().format(record)
        color = _LEVEL_COLORS.get(record.levelname, '')
        if not color:
            return super().format(record)
        original = record.levelname
        record.levelname = f'{color}{original}{_ANSI_RESET}'
        try:
            return super().format(record)
        finally:
            record.levelname = original


def _color_supported(stream: typing.IO[str]) -> bool:
    """True iff it's polite to emit ANSI escapes to `stream`.

    Two opt-outs are honored:
      * `stream.isatty()` is False -- the output is being captured (file,
        pipe, CI runner), where escape bytes would clutter the artifact.
      * `NO_COLOR` is set in the environment -- de-facto standard
        (see https://no-color.org) for users / tools that universally
        want plain text.
    """
    return stream.isatty() and 'NO_COLOR' not in os.environ


# Third-party loggers that go DEBUG-loud the moment the root logger drops
# below INFO. The noise they add ("Starting new HTTP connection (1):
# localhost:8000", connection pool debug, etc.) buries our own progress
# lines and tells the user nothing they can act on, so we pin them to
# WARNING regardless of how verbose the rest of the CLI is.
_NOISY_THIRD_PARTY_LOGGERS: typing.Final[tuple[str, ...]] = (
    'urllib3',
    'urllib3.connectionpool',
    'aiohttp',
    'asyncio',
)


def configure(level: int = logging.DEBUG) -> None:
    """Install the colorized stdout handler on the root logger.

    Defaults to `DEBUG` because the CLI's call sites (notably the upload
    loop) deliberately demote high-frequency progress lines to DEBUG and
    rely on the cyan tint -- not on filtering -- to fade them into the
    background. Callers wanting a quieter run can pass `logging.INFO`.

    Safe to call once at process start; relies on `logging.basicConfig`'s
    "no-op if root already configured" behavior so re-imports don't stack
    duplicate handlers.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_LevelColorFormatter(
        fmt=_DEFAULT_FMT,
        datefmt=_DEFAULT_DATEFMT,
        use_color=_color_supported(sys.stdout),
    ))
    logging.basicConfig(level=level, handlers=[handler])

    for noisy in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
