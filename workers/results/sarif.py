from __future__ import annotations

import typing
import dataclasses

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

@dataclasses.dataclass(frozen=True)
class Driver:

    name: str

@dataclasses.dataclass(frozen=True)
class SarifMessage:

    text: str

@dataclasses.dataclass(frozen=True, kw_only=True)
class Region:

    startLine: int
    endLine: int
    startColumn: int
    endColumn: int

    @staticmethod
    def make_default() -> Region:
        return Region(
            startLine=0,
            endLine=0,
            startColumn=0,
            endColumn=0
        )

@dataclasses.dataclass(frozen=True)
class ArtifactLocation:

    uri: str

@dataclasses.dataclass(frozen=True)
class PhysicalLocation:

    artifactLocation: ArtifactLocation
    region: Region

@dataclasses.dataclass(frozen=True)
class SarifLocation:

    physicalLocation: PhysicalLocation

@dataclasses.dataclass(frozen=True)
class ThreadFlowLocation:

    location: SarifLocation

@dataclasses.dataclass(frozen=True)
class ThreadFlow:

    locations: list[ThreadFlowLocation]

@dataclasses.dataclass(frozen=True)
class CodeFlow:

    threadFlows: list[ThreadFlow]

@dataclasses.dataclass(frozen=True, kw_only=True)
class SarifResult:

    ruleId: str
    message: SarifMessage
    locations: list[SarifLocation]
    codeFlows: typing.Optional[list[CodeFlow]]

@dataclasses.dataclass(frozen=True)
class SarifTool:

    driver: Driver

@dataclasses.dataclass(frozen=True, kw_only=True)
class SarifRun:

    tool: SarifTool
    results: list[SarifResult]

@dataclasses.dataclass(frozen=True)
class Sarif:

    version: str
    runs: list[SarifRun]

def empty() -> Sarif:
    driver = Driver('dhscanner')
    dhscanner = SarifTool(driver)
    runs = [SarifRun(tool=dhscanner,results=[])]
    return Sarif('2.1.0', runs)

# pylint: disable=too-many-locals
def run(*, path: list[Location], description: str) -> Sarif:
    driver = Driver('dhscanner')
    dhscanner = SarifTool(driver)

    thread_flow_locs = []
    for loc in path:
        region = Region(
            startLine=loc.lineStart,
            endLine=loc.lineEnd,
            startColumn=loc.colStart,
            endColumn=loc.colEnd
        )
        artifact_location = ArtifactLocation(uri=loc.filename)
        physical_location = PhysicalLocation(
            artifactLocation=artifact_location,
            region=region
        )
        thread_flow_locs.append(ThreadFlowLocation(
            location=SarifLocation(physical_location)
        ))

    thread_flow = ThreadFlow(locations=thread_flow_locs)
    code_flows = [CodeFlow(threadFlows=[thread_flow])]

    final_location = thread_flow_locs[-1].location

    result = SarifResult(
        ruleId='dataflow',
        message=SarifMessage(text=description),
        locations=[final_location],
        codeFlows=code_flows
    )

    run = SarifRun(tool=dhscanner, results=[result])
    return Sarif(version='2.1.0', runs=[run])
