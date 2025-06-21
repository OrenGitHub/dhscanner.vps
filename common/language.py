from __future__ import annotations

import enum
import typing
import pathlib

class Language(str, enum.Enum):

    JS = 'js'
    TS = 'ts'
    TSX = 'tsx'
    PHP = 'php'
    PY = 'py'
    RB = 'rb'
    CS = 'cs'
    GO = 'go'
    BLADE_PHP = 'blade.php'
    ALL = 'ALL'
    UNKNOWN = 'UNKNOWN'

    @staticmethod
    def from_raw_str(raw: str) -> typing.Optional[Language]:
        try:
            return Language(raw)
        except ValueError:
            return None

    @staticmethod
    def from_filename(filename: str) -> typing.Optional[Language]:
        suffixes = pathlib.Path(filename).suffixes
        extension = "".join(suffixes)
        if extension.startswith('.'):
            return Language.from_raw_str(extension.lstrip('.'))

        return None
