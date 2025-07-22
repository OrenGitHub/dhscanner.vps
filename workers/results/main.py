import re
import typing
import dataclasses

from common.language import Language
from coordinator.interface import Status
from workers.interface import AbstractWorker

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
            filename=candidate['filename'],
            lineStart=candidate['lineStart'],
            lineEnd=candidate['lineEnd'],
            colStart=candidate['colStart'],
            colEnd=candidate['colEnd']
        )

START = r'startloc_(\d+)_(\d+)'
END = r'endloc_(\d+)_(\d+)'
FNAME = r'([^,]+)'
LOC = fr'{START}_{END}_{FNAME}'
EDGE = fr'\({LOC},{LOC}\)'
FINDING = r'q(\d+)\(\[(.*?)\]\): yes'
EDGES_GROUP_IDX_IN_FINDING = 2

@dataclasses.dataclass(frozen=True)
class Results(AbstractWorker):

    # pylint: disable=too-many-locals
    @typing.override
    async def run(self, job_id: str) -> None:
        key = self.the_storage_guy.load_results_metadata_from_db(job_id)
        content = await self.the_storage_guy.load_results(key)
        if ': yes' in content:
            p = Results.parse_proper_path(content)
            print(p, flush=True)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.Finished
            )

    @staticmethod
    def parse_proper_path(content: str) -> list[Location]:
        locations = []
        if proper_path := re.search(FINDING, content):
            edges = proper_path.group(EDGES_GROUP_IDX_IN_FINDING)
            all_edges = re.findall(EDGE, edges)
            n = len(all_edges)
            for i, edge in enumerate(all_edges):
                locations.append(
                    Location(
                        filename=Results.restore(edge[4]),
                        lineStart=int(edge[0]),
                        colStart=int(edge[1]),
                        lineEnd=int(edge[2]),
                        colEnd = int(edge[3])
                    )
                )
                if i == n - 1:
                    locations.append(
                        Location(
                            filename=Results.restore(edge[9]),
                            lineStart=int(edge[5]),
                            colStart=int(edge[6]),
                            lineEnd=int(edge[7]),
                            colEnd = int(edge[8])
                        )
                    )
            return locations

    @staticmethod
    def restore(filename: str) -> str:
        return (
            filename
            .replace('_slash_', '/')
            .replace('_dot_', '.')
            .replace('_dash_', '-')
            .replace('_lbracket_', '[')
            .replace('_rbracket_', ']')
            .replace('_lparen_', '(')
            .replace('_rparen_', ')')
        )
