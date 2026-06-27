from __future__ import annotations

import socket
import typing
import pathlib
import argparse
import dataclasses

from urllib.parse import urlparse

CLI_PROG_DESC: typing.Final[str] = """

simple dev script to send repo for dhscanner inspection
"""

CLI_RUN_DESC: typing.Final[str] = """
scan a directory: allocate a job id, upload files, run analysis, fetch sarif
"""

CLI_MANAGE_DESC: typing.Final[str] = """
operator-mode helpers: list / clear jobs on the server
"""

CLI_SCAN_DIRNAME_HELP: typing.Final[str] = """
relative / absolute path of the dir you want to scan
"""

CLI_IGNORE_TESTING_CODE_HELP: typing.Final[str] = """
ignore testing code
"""

CLI_SAVE_SARIF_OUTPUT_HELP: typing.Final[str] = """
save the output in sarif format
"""

CLI_USE_EXTERNAL_VPS: typing.Final[str] = """
connect to an external virtual private server
"""

CLI_WITH_AGENT: typing.Final[str] = """
use an LLM agent for adaptive query planning
"""

CLI_GET_ALL_JOB_IDS_HELP: typing.Final[str] = """
list every job id the server still knows about, then exit
(useful for prefix/suffix cross-ref, cleanup, ad-hoc log queries)
"""

CLI_CLEAR_JOB_ID_HELP: typing.Final[str] = """
wipe one job from redis + sqlite + the shared volume + pg logs, then exit
"""

CLI_CLEAR_ALL_HELP: typing.Final[str] = """
wipe every job from redis + sqlite + the shared volume + pg logs, then exit
"""


def non_empty_job_id(candidate: str) -> str:
    # Sanity: redis keys are case-sensitive and stripping silently could
    # produce a no-op DELETE when the user typo'd a trailing space.
    stripped = candidate.strip()
    if not stripped:
        raise argparse.ArgumentTypeError('job id cannot be empty')
    if stripped != candidate:
        raise argparse.ArgumentTypeError('job id has surrounding whitespace')
    return stripped

EXPLORE_WITH_AGENT_PROG_DESC: typing.Final[str] = """

simple dev script to run kb api queries
"""

EXPLORE_WITH_AGENT_USE_KB_HELP: typing.Final[str] = """
kb filename returned from cli.py run --with_agent flow
"""

HTTPS_PORT: typing.Final[int] = 443


def existing_non_empty_dirname(name: str) -> pathlib.Path:
    candidate = pathlib.Path(name)

    if not candidate.is_dir():
        message = f'directory {name} does not exist'
        raise argparse.ArgumentTypeError(message)

    if not any(candidate.iterdir()):
        message = f'no files found in directory: {name}'
        raise argparse.ArgumentTypeError(message)

    return candidate


def proper_bool_value(name: str) -> bool:
    if name not in ['true', 'false']:
        message = 'please specify true | false for including testing code'
        raise argparse.ArgumentTypeError(message)

    return name == 'true'


def valid_output_file(output: str) -> pathlib.Path:
    candidate = pathlib.Path(output)

    try:
        with open(candidate, 'w', encoding='utf-8'):
            pass
    # pylint: disable=raise-missing-from
    except IsADirectoryError:
        raise argparse.ArgumentTypeError(f'{candidate} is not a file ( directory given )')
    except PermissionError:
        raise argparse.ArgumentTypeError(f'no write permission for: {candidate}')

    return candidate


def valid_external_vps(candidate: str) -> str:
    if not candidate.startswith('https://'):
        message = 'url must start with https://'
        raise argparse.ArgumentTypeError(message)

    url = urlparse(candidate)
    hostname = url.hostname

    if hostname is None:
        message = f'missing host in {candidate}'
        raise argparse.ArgumentTypeError(message)

    try:
        with socket.create_connection((hostname, HTTPS_PORT), timeout=2.0):
            pass
    except OSError:
        message = f'unreachable: {hostname}'
        # pylint: disable=raise-missing-from
        raise argparse.ArgumentTypeError(message)

    return candidate


def non_empty_kb_filename(kb_filename: str) -> str:
    if kb_filename.strip() == '':
        raise argparse.ArgumentTypeError('kb filename cannot be empty')
    return kb_filename


@dataclasses.dataclass(frozen=True, kw_only=True)
class CliArgparse:
    # Base class: only the fields *every* subcommand shares. Right now
    # that's just --use_external_vps (both 'run' and 'manage' need to
    # know which host to talk to). Subcommand-specific fields live on
    # the concrete subclasses below; downstream code dispatches via
    # isinstance() against those subclasses, so each call path is
    # type-narrowed (no more Optional-everywhere on the dataclass).
    use_external_vps: typing.Optional[str]

    @staticmethod
    def parse() -> CliRunArgparse | CliManageArgparse:
        parser = argparse.ArgumentParser(description=CLI_PROG_DESC)

        # Args shared by every subcommand live on a parent parser so we
        # define them once. Right now that's just --use_external_vps.
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument(
            '--use_external_vps',
            required=False,
            type=valid_external_vps,
            metavar='https://dhscanner.org',
            help=CLI_USE_EXTERNAL_VPS,
        )

        subparsers = parser.add_subparsers(
            dest='command',
            required=True,
            metavar='{run,manage}',
        )

        # ---- run: scan a directory --------------------------------------
        run_parser = subparsers.add_parser(
            'run',
            parents=[common],
            description=CLI_RUN_DESC,
            help='scan a directory',
        )
        run_parser.add_argument(
            '--scan_dirname',
            required=True,
            type=existing_non_empty_dirname,
            metavar='dir/you/want/to/scan',
            help=CLI_SCAN_DIRNAME_HELP,
        )
        run_parser.add_argument(
            '--ignore_testing_code',
            required=True,
            type=proper_bool_value,
            metavar='true | false',
            help=CLI_IGNORE_TESTING_CODE_HELP,
        )
        run_parser.add_argument(
            '--save_sarif_to',
            required=False,
            type=valid_output_file,
            metavar='save/sarif/to/output.json',
            help=CLI_SAVE_SARIF_OUTPUT_HELP,
        )
        run_parser.add_argument(
            '--with_agent',
            required=False,
            default=False,
            action='store_true',
            help=CLI_WITH_AGENT,
        )

        # ---- manage: operator helpers -----------------------------------
        # The three operations are mutually exclusive *and* one is
        # required (otherwise `cli.py manage` would be a no-op). Both
        # constraints are expressed natively by argparse via the
        # mutually-exclusive group with required=True.
        manage_parser = subparsers.add_parser(
            'manage',
            parents=[common],
            description=CLI_MANAGE_DESC,
            help='list / clear jobs on the server',
        )
        ops = manage_parser.add_mutually_exclusive_group(required=True)
        ops.add_argument(
            '--get-all-job-ids',
            default=False,
            action='store_true',
            help=CLI_GET_ALL_JOB_IDS_HELP,
        )
        ops.add_argument(
            '--clear-job-id',
            default=None,
            type=non_empty_job_id,
            metavar='<job_id>',
            help=CLI_CLEAR_JOB_ID_HELP,
        )
        ops.add_argument(
            '--clear-all',
            default=False,
            action='store_true',
            help=CLI_CLEAR_ALL_HELP,
        )

        ns = parser.parse_args()

        # Dispatch the parsed Namespace into the right concrete
        # subclass. argparse already guaranteed `ns.command` is one of
        # {'run', 'manage'} via `required=True` on the subparsers
        # group, so the else-branch is exhaustive (no fallthrough).
        if ns.command == 'run':
            return CliRunArgparse(
                use_external_vps=ns.use_external_vps,
                scan_dirname=ns.scan_dirname,
                ignore_testing_code=ns.ignore_testing_code,
                save_sarif_to=ns.save_sarif_to,
                with_agent=ns.with_agent,
            )

        return CliManageArgparse(
            use_external_vps=ns.use_external_vps,
            get_all_job_ids=ns.get_all_job_ids,
            clear_job_id=ns.clear_job_id,
            clear_all=ns.clear_all,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class CliRunArgparse(CliArgparse):
    # Scan-mode args. scan_dirname / ignore_testing_code are
    # non-Optional here because argparse already enforced
    # required=True on the 'run' subparser — by the time we
    # construct this class, both fields are guaranteed to be set.
    scan_dirname: pathlib.Path
    ignore_testing_code: bool
    save_sarif_to: typing.Optional[pathlib.Path]
    with_agent: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class CliManageArgparse(CliArgparse):
    # Operator-mode discriminators. Exactly one of these three is set
    # to its non-default value (True / a job id string) — argparse's
    # mutually-exclusive group with required=True guarantees that.
    get_all_job_ids: bool
    clear_job_id: typing.Optional[str]
    clear_all: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExploreWithAgentArgparse:
    use_kb: str
    save_sarif_to: pathlib.Path

    @staticmethod
    def run() -> ExploreWithAgentArgparse:
        parser = argparse.ArgumentParser(description=EXPLORE_WITH_AGENT_PROG_DESC)

        parser.add_argument(
            '--use_kb',
            required=True,
            type=non_empty_kb_filename,
            metavar='kb_filename',
            help=EXPLORE_WITH_AGENT_USE_KB_HELP,
        )

        parser.add_argument(
            '--save_sarif_to',
            required=True,
            type=valid_output_file,
            metavar='save/sarif/to/output.json',
            help=CLI_SAVE_SARIF_OUTPUT_HELP,
        )

        parsed_args = parser.parse_args()
        return ExploreWithAgentArgparse(
            use_kb=parsed_args.use_kb,
            save_sarif_to=parsed_args.save_sarif_to,
        )
