from __future__ import annotations

import sys
import json
import http
import typing
import pathlib
import logging

import requests

from argparse_wrapper import ExploreWithAgentArgparse as Argparse

QUERYENGINE_API_URL: typing.Final[str] = 'http://localhost:3000/api'

DEFAULT_QUERY_BODY: typing.Final[dict[str, typing.Any]] = {
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


def run_query(use_kb: str) -> typing.Optional[dict]:
    params = {'kb_location': use_kb}

    try:
        with requests.post(QUERYENGINE_API_URL, params=params, json=DEFAULT_QUERY_BODY, timeout=30) as response:
            if response.status_code != http.HTTPStatus.OK:
                logging.error('kb api failed with status %s', response.status_code)
                return None
            return response.json()
    except requests.exceptions.RequestException as exc:
        logging.error('failed calling kb api: %s', exc)
    except json.JSONDecodeError:
        logging.error('kb api returned invalid json')

    return None


def save_json(output: pathlib.Path, content: dict) -> None:
    with output.open('w', encoding='utf-8') as fl:
        json.dump(content, fl)


def main(parsed_args: Argparse) -> None:
    logging.info('[ step 0 ] required args ok 😊')
    logging.info('[ step 1 ] running kb api query')
    if results := run_query(parsed_args.use_kb):
        save_json(parsed_args.save_sarif_to, results)
        logging.info('[ step 2 ] saved kb api output to: %s', parsed_args.save_sarif_to)


if __name__ == '__main__':
    if args := Argparse.run():
        main(args)
