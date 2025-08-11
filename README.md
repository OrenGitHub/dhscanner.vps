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
$ docker compose \
-f ./compose/compose.base.yaml \
-f ./compose/compose.app.yaml \
-f ./compose/compose.fronts.yaml \
-f ./compose/compose.prebuilt.yaml \
-f ./compose/compose.workers.yaml up -d

# install dependencies
$ pipenv shell
$ pipenv install

# start scanning 🙂
$ python ./cli.py --scan_dirname repo/you/want/to/scan --ignore_testing_code true
```
