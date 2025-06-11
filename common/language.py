from __future__ import annotations

import enum
import typing

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