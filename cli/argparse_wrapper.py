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

CLI_LAUNCH_LOCAL_APP_DESC: typing.Final[str] = """
agent-driven helper: inspect a local repo, propose a launch plan, run it,
probe a healthcheck url, and on failure feed the errors back to the model
for a follow-up plan (up to --max-iterations attempts)
"""

CLI_LAUNCH_TARGET_DIR_HELP: typing.Final[str] = """
relative / absolute path of the target app's repo (e.g. ../phpbb)
"""

CLI_LAUNCH_MODEL_HELP: typing.Final[str] = """
openai chat model used to plan the launch (default: gpt-5 or $OPENAI_MODEL)
"""

CLI_LAUNCH_MAX_ITERATIONS_HELP: typing.Final[str] = """
upper bound on plan -> run -> probe -> feedback iterations (default: 5)
"""

CLI_LAUNCH_OPENAI_TIMEOUT_HELP: typing.Final[str] = """
per-call openai timeout in seconds (default: 180)
"""

CLI_LAUNCH_PROBE_DELAY_HELP: typing.Final[str] = """
seconds to wait after launch_command before the first healthcheck probe
(default: 5)
"""

CLI_LAUNCH_DRY_RUN_HELP: typing.Final[str] = """
ask the model for a plan and print it, but do not run any command
"""

CLI_LAUNCH_TEARDOWN_HELP: typing.Final[str] = """
run the final accepted plan's cleanup_commands at exit even on success
(default: leave the app running so the next loop step can talk to it)
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
kb filename returned from `python -m cli run --with_agent` flow
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


def positive_int(raw: str) -> int:
    # Used by --max-iterations: argparse already takes care of the
    # int parse; we just refuse 0/negative so a typo can't silently
    # turn the whole launch loop into a no-op.
    try:
        value = int(raw)
    # pylint: disable=raise-missing-from
    except ValueError:
        raise argparse.ArgumentTypeError(f'not an int: {raw}')
    if value < 1:
        raise argparse.ArgumentTypeError(f'must be >= 1, got {value}')
    return value


def positive_float(raw: str) -> float:
    # Same intent as positive_int, but for the timeout/delay knobs.
    try:
        value = float(raw)
    # pylint: disable=raise-missing-from
    except ValueError:
        raise argparse.ArgumentTypeError(f'not a number: {raw}')
    if value <= 0.0:
        raise argparse.ArgumentTypeError(f'must be > 0, got {value}')
    return value


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
    def parse() -> CliRunArgparse | CliManageArgparse | CliLaunchLocalAppArgparse:
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
            metavar='{run,manage,launch-local-app}',
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

        # ---- launch-local-app: agent-driven launcher --------------------
        # Doesn't take --use_external_vps because it only ever drives a
        # local subprocess + a localhost healthcheck; an external vps is
        # the dhscanner side, not the target app being launched. The
        # positional `target_dir` mirrors the way users naturally call
        # this from the shell (`python -m cli launch-local-app ../phpbb`).
        launch_parser = subparsers.add_parser(
            'launch-local-app',
            description=CLI_LAUNCH_LOCAL_APP_DESC,
            help='agent-driven local app launcher',
        )
        launch_parser.add_argument(
            'target_dir',
            type=existing_non_empty_dirname,
            metavar='path/to/target/app',
            help=CLI_LAUNCH_TARGET_DIR_HELP,
        )
        launch_parser.add_argument(
            '--model',
            required=False,
            default=None,
            metavar='gpt-5',
            help=CLI_LAUNCH_MODEL_HELP,
        )
        launch_parser.add_argument(
            '--max-iterations',
            required=False,
            type=positive_int,
            default=5,
            metavar='N',
            help=CLI_LAUNCH_MAX_ITERATIONS_HELP,
        )
        launch_parser.add_argument(
            '--openai-timeout',
            required=False,
            type=positive_float,
            default=180.0,
            metavar='SECONDS',
            help=CLI_LAUNCH_OPENAI_TIMEOUT_HELP,
        )
        launch_parser.add_argument(
            '--probe-delay',
            required=False,
            type=positive_float,
            default=5.0,
            metavar='SECONDS',
            help=CLI_LAUNCH_PROBE_DELAY_HELP,
        )
        launch_parser.add_argument(
            '--dry-run',
            required=False,
            default=False,
            action='store_true',
            help=CLI_LAUNCH_DRY_RUN_HELP,
        )
        launch_parser.add_argument(
            '--teardown-on-exit',
            required=False,
            default=False,
            action='store_true',
            help=CLI_LAUNCH_TEARDOWN_HELP,
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

        if ns.command == 'launch-local-app':
            # No --use_external_vps for this command (see the subparser
            # definition above for why); pass None to satisfy the base
            # class without piggybacking unrelated semantics on it.
            return CliLaunchLocalAppArgparse(
                use_external_vps=None,
                target_dir=ns.target_dir,
                model=ns.model,
                max_iterations=ns.max_iterations,
                openai_timeout=ns.openai_timeout,
                probe_delay=ns.probe_delay,
                dry_run=ns.dry_run,
                teardown_on_exit=ns.teardown_on_exit,
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
class CliLaunchLocalAppArgparse(CliArgparse):
    # Agent-driven launcher knobs. target_dir is the only required
    # input; the rest tune the iteration loop. `model` is Optional so
    # the launcher module can fall back to $OPENAI_MODEL / its own
    # default without the argparse layer needing to know either of
    # those values (keeps env lookups out of the parser).
    target_dir: pathlib.Path
    model: typing.Optional[str]
    max_iterations: int
    openai_timeout: float
    probe_delay: float
    dry_run: bool
    teardown_on_exit: bool


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
