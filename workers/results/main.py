import re
import typing
import dataclasses

from workers.results import sarif
from coordinator.interface import Status
from workers.interface import AbstractWorker

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
        sarif_results = {'debug': 'query engine failed'}
        if ': yes' in content:
            p = Results.parse_proper_path(content)
            sarif_results = Results.generate_sarif_from_path(p)

        await self.the_storage_guy.save_output(sarif_results, job_id)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.Finished
            )

    @staticmethod
    def parse_proper_path(content: str) -> list[sarif.Location]:
        locations = []
        if proper_path := re.search(FINDING, content):
            edges = proper_path.group(EDGES_GROUP_IDX_IN_FINDING)
            all_edges = re.findall(EDGE, edges)
            n = len(all_edges)
            for i, edge in enumerate(all_edges):
                locations.append(
                    sarif.Location(
                        filename=Results.restore(edge[4]),
                        lineStart=int(edge[0]),
                        colStart=int(edge[1]),
                        lineEnd=int(edge[2]),
                        colEnd = int(edge[3])
                    )
                )
                if i == n - 1:
                    locations.append(
                        sarif.Location(
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

    @staticmethod
    def generate_sarif_from_path(p: list[sarif.Location]) -> dict:
        output = sarif.run(path=p, description='owasp top 10')
        return dataclasses.asdict(output)
