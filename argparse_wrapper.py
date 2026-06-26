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
kb filename returned from cli.py --with_agent flow
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
    # All of these are Optional because of the operator-mode flags
    # (--get-all-job-ids / --clear-job-id / --clear-all): in those modes
    # the user just wants to poke the server and shouldn't be forced to
    # point at a scan dir / pick a test policy they have no intention of
    # using. The "must be set in scan mode" contract is enforced after
    # parsing, not by argparse's required=.
    scan_dirname: typing.Optional[pathlib.Path]
    ignore_testing_code: typing.Optional[bool]
    save_sarif_to: typing.Optional[pathlib.Path]
    use_external_vps: typing.Optional[str]
    with_agent: bool
    get_all_job_ids: bool
    clear_job_id: typing.Optional[str]
    clear_all: bool

    @staticmethod
    def run() -> CliArgparse:
        parser = argparse.ArgumentParser(description=CLI_PROG_DESC)

        parser.add_argument(
            '--scan_dirname',
            required=False,
            type=existing_non_empty_dirname,
            metavar='dir/you/want/to/scan',
            help=CLI_SCAN_DIRNAME_HELP,
        )

        parser.add_argument(
            '--ignore_testing_code',
            required=False,
            type=proper_bool_value,
            metavar='true | false',
            help=CLI_IGNORE_TESTING_CODE_HELP,
        )

        parser.add_argument(
            '--save_sarif_to',
            required=False,
            type=valid_output_file,
            metavar='save/sarif/to/output.json',
            help=CLI_SAVE_SARIF_OUTPUT_HELP,
        )

        parser.add_argument(
            '--use_external_vps',
            required=False,
            type=valid_external_vps,
            metavar='https://dhscanner.org',
            help=CLI_USE_EXTERNAL_VPS,
        )

        parser.add_argument(
            '--with_agent',
            required=False,
            default=False,
            action='store_true',
            help=CLI_WITH_AGENT,
        )

        # Operator-mode flags live in a mutually-exclusive group so the
        # user can't accidentally ask the CLI to "list jobs AND clear
        # them" in one invocation. argparse handles the exclusion check
        # automatically; we still need the post-parse "scan args required
        # unless any of these is set" guard below.
        ops = parser.add_mutually_exclusive_group()
        ops.add_argument(
            '--get-all-job-ids',
            required=False,
            default=False,
            action='store_true',
            help=CLI_GET_ALL_JOB_IDS_HELP,
        )
        ops.add_argument(
            '--clear-job-id',
            required=False,
            default=None,
            type=non_empty_job_id,
            metavar='<job_id>',
            help=CLI_CLEAR_JOB_ID_HELP,
        )
        ops.add_argument(
            '--clear-all',
            required=False,
            default=False,
            action='store_true',
            help=CLI_CLEAR_ALL_HELP,
        )

        parsed_args = parser.parse_args()

        # Conditional required-ness: scan-mode still needs both anchors,
        # operator-mode needs neither. argparse can't express "required
        # unless any-of-flags-X" natively, so the check lives here and
        # uses the same error() channel so the CLI keeps its single
        # usage line.
        operator_mode = (
            parsed_args.get_all_job_ids
            or parsed_args.clear_job_id is not None
            or parsed_args.clear_all
        )
        if not operator_mode:
            missing = [
                name for name, value in (
                    ('--scan_dirname', parsed_args.scan_dirname),
                    ('--ignore_testing_code', parsed_args.ignore_testing_code),
                ) if value is None
            ]
            if missing:
                parser.error(
                    'the following arguments are required (unless one of '
                    '--get-all-job-ids / --clear-job-id / --clear-all is set): '
                    f'{", ".join(missing)}'
                )

        return CliArgparse(
            scan_dirname=parsed_args.scan_dirname,
            ignore_testing_code=parsed_args.ignore_testing_code,
            save_sarif_to=parsed_args.save_sarif_to,
            use_external_vps=parsed_args.use_external_vps,
            with_agent=parsed_args.with_agent,
            get_all_job_ids=parsed_args.get_all_job_ids,
            clear_job_id=parsed_args.clear_job_id,
            clear_all=parsed_args.clear_all,
        )


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
