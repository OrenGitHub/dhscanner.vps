[![pylint](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml)
[![mypy](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml)
[![tests](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml)

## dhscanner.vps

optimized backend for dhscanner

## install

```bash
$ git clone --recurse-submodules https://github.com/OrenGitHub/dhscanner.vps.git
$ cd dhscanner.vps

# about 3 min. on a modern laptop
$ docker compose -f ./compose/compose.base.yaml -f ./compose/compose.app.yaml -f ./compose/compose.fronts.yaml -f ./compose/compose.prebuilt.yaml -f ./compose/compose.workers.yaml up -d

# install dependencies
$ pipenv shell
$ pipenv install

# start scanning 🙂
$ python ./cli.py run --scan_dirname repo/you/want/to/scan --ignore_testing_code true
```

## operator commands

Read-only listing and full wipes for the jobs the server still knows about.
All three operations live under the `manage` subcommand and talk to the same
server you scan against (add `--use_external_vps https://...` for a remote vps).

```bash
# list every job id still tracked by redis (one per line, greppable)
$ python ./cli.py manage --get-all-job-ids

# wipe one job: redis + sqlite + shared volume + postgres logger rows
$ python ./cli.py manage --clear-job-id <job_id>

# wipe every job (same scope as above, applied to all jobs)
$ python ./cli.py manage --clear-all
```

The three are mutually exclusive (exactly one is required under `manage`),
and `manage` doesn't take the scan-mode flags. Third-party trees (`vendor`,
`node_modules`, `site_packages`) are pruned automatically during scan-mode
collection.
