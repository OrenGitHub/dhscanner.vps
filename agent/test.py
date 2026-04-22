from __future__ import annotations

import sys
import json
import http
import typing
import pathlib
import logging

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from argparse_wrapper import ExploreWithAgentArgparse as Argparse

QUERYENGINE_API_URL: typing.Final[str] = 'http://localhost:3000/api'

CONST_STRINGS_MATCHING_QUERY: typing.Final[dict[str, typing.Any]] = {
    'tag': 'ConstStringsMatching',
    'contents': {
        'constStringsMatchingThisRegex': '.*',
        'constStringsMatchingLimit': 200,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s]: %(message)s',
    datefmt='%d/%m/%Y ( %H:%M:%S )',
    stream=sys.stdout,
)


def valid_const_strings_response(response_json: dict[str, typing.Any]) -> bool:
    if response_json.get('tag') != 'FoundConstStringsMatching':
        logging.error('unexpected tag in response: %s', response_json.get('tag'))
        return False

    contents = response_json.get('contents')
    if not isinstance(contents, dict):
        logging.error('response contents is missing or invalid')
        return False

    regex = contents.get('foundConstStringsMatchingThisRegex')
    total = contents.get('foundConstStringsMatchesTotal')
    matches = contents.get('foundConstStringsMatches')

    if not isinstance(regex, str):
        logging.error('invalid foundConstStringsMatchingThisRegex: %s', regex)
        return False
    if not isinstance(total, int):
        logging.error('invalid foundConstStringsMatchesTotal: %s', total)
        return False
    if not isinstance(matches, list):
        logging.error('invalid foundConstStringsMatches: %s', matches)
        return False

    return True


def log_const_strings_preview(response_json: dict[str, typing.Any], preview_limit: int = 10) -> None:
    contents = response_json['contents']
    total = contents['foundConstStringsMatchesTotal']
    matches = contents['foundConstStringsMatches']
    regex = contents['foundConstStringsMatchingThisRegex']

    logging.info('[ test ] regex used: %s', regex)
    logging.info('[ test ] total matched strings: %s', total)

    if not matches:
        logging.info('[ test ] no constant strings matched')
        return

    logging.info('[ test ] showing first %s matches:', min(preview_limit, len(matches)))
    for i, match in enumerate(matches[:preview_limit], start=1):
        value = match.get('foundConstStringMatchValue', '<missing value>')
        location = match.get('foundConstStringMatchLocation', {})
        filename = location.get('filename', '<unknown file>')
        logging.info('  #%s value=%s file=%s', i, value, filename)


def run_const_strings_query(kb_filename: str) -> typing.Optional[dict[str, typing.Any]]:
    params = {'kb_location': kb_filename}

    try:
        with requests.post(
            QUERYENGINE_API_URL,
            params=params,
            json=CONST_STRINGS_MATCHING_QUERY,
            timeout=30,
        ) as response:
            if response.status_code != http.HTTPStatus.OK:
                logging.error('query api failed with status %s', response.status_code)
                return None
            return response.json()
    except requests.exceptions.RequestException as exc:
        logging.error('query api call failed: %s', exc)
        logging.error(
            'make sure queryengine is running and host port 3000 is exposed '
            '(e.g. compose queryengine service has ports: ["3000:3000"])'
        )
    except json.JSONDecodeError:
        logging.error('query api returned invalid json')

    return None


def main(parsed_args: Argparse) -> int:
    logging.info('[ test ] sending ConstStringsMatching query')
    if not (response_json := run_const_strings_query(parsed_args.use_kb)):
        return 1

    if not valid_const_strings_response(response_json):
        return 1

    log_const_strings_preview(response_json)

    with parsed_args.save_sarif_to.open('w', encoding='utf-8') as fl:
        json.dump(response_json, fl)

    logging.info('[ test ] response is valid and saved to %s', parsed_args.save_sarif_to)
    return 0


if __name__ == '__main__':
    if args := Argparse.run():
        raise SystemExit(main(args))
