import dataclasses
import re
import typing


def patternify(suffix: str) -> str:
    start = r'startloc_(\d+)_(\d+)'
    end = r'endloc_(\d+)_(\d+)'
    fname = fr'([^,]+_dot_{suffix})'
    loc = fr'{start}_{end}_{fname}'
    edge = fr'\({loc},{loc}\)'
    path = fr'{edge}(,{edge})*'
    query = r'q(\d+)'
    return fr'{query}\(\[{path}\]\): yes'

def sinkify(match: re.Match, filename: str, offsets: dict[str, dict[int, int]]) -> typing.Optional[generate_sarif.Region]:

    n = len(match.groups())
    for i in reversed(range(5, n)):

        try:
            locs = [int(match.group(i-d)) for d in reversed(range(4))]
        except (ValueError, TypeError):
            continue

        return generate_sarif.Region(
            startLine=locs[0],
            startColumn=normalize(filename, locs[0], locs[1], offsets),
            endLine=locs[2],
            endColumn=normalize(filename, locs[2], locs[3], offsets)
        )

    return None

@dataclasses.dataclass(kw_only=True, frozen=True)
class Location:

    filename: str
    lineStart: int
    lineEnd: int
    colStart: int
    colEnd: int

    def __str__(self) -> str:
        return f'[{self.lineStart}:{self.colStart}-{self.lineEnd}:{self.colEnd}]'

    @staticmethod
    def from_dict(candidate: dict) -> typing.Optional['Location']:

        if 'filename' not in candidate:
            return None
        if 'lineStart' not in candidate:
            return None
        if 'lineEnd' not in candidate:
            return None
        if 'colStart' not in candidate:
            return None
        if 'colEnd' not in candidate:
            return None

        return Location(
            filename=remove_tmp_prefix(candidate['filename']),
            lineStart=candidate['lineStart'],
            lineEnd=candidate['lineEnd'],
            colStart=candidate['colStart'],
            colEnd=candidate['colEnd']
        )

def restore(filename: str) -> str:
    return filename.replace('_slash_', '/').replace('_dot_', '.').replace('_dash_', '-')

def normalize(filename: str, line: int, offset: int, offsets) -> int:
    if filename in offsets:
        if line in offsets[filename]:
            if offset >= offsets[filename][line]:
                return offset - offsets[filename][line] + 1

    return offset
