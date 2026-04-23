from __future__ import annotations

import sys
import json
import http
import typing
import logging

import requests

try:
    from argparse_wrapper import ExploreWithAgentArgparse as Argparse
except ModuleNotFoundError as exc:
    if exc.name == 'argparse_wrapper':
        raise SystemExit(
            'argparse_wrapper is not importable. Run from repo root with '
            '`python -m agent.test --use_kb ... --save_sarif_to ...`'
        ) from exc
    raise

QUERYENGINE_API_URL: typing.Final[str] = 'http://localhost:3000/api'

CONST_STRINGS_MATCHING_QUERY: typing.Final[dict[str, typing.Any]] = {
    'tag': 'ConstStringsMatching',
    'contents': {
        'constStringsMatchingThisRegex': '.*',
        'constStringsMatchingLimit': 7,
    },
}

HTTP_POST_HANDLER_REQUEST_OBJECT_QUERY: typing.Final[dict[str, typing.Any]] = {
    'tag': 'HttpPostHandlerRequestObject',
    'contents': {
        'httpPostHandlerRequestObjectUrlParts': [],
        'httpPostHandlerRequestObjectLimit': 5,
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


def is_valid_location(location: typing.Any) -> bool:
    if not isinstance(location, dict):
        return False

    required_keys = ['filename', 'lineStart', 'lineEnd', 'colStart', 'colEnd']
    for key in required_keys:
        if key not in location:
            return False

    if not isinstance(location['filename'], str):
        return False

    if not all(isinstance(location[key], int) for key in required_keys[1:]):
        return False

    return True


def valid_http_post_handler_request_object_response(response_json: dict[str, typing.Any]) -> bool:
    if response_json.get('tag') != 'FoundHttpPostHandlerRequestObject':
        logging.error('unexpected tag in response: %s', response_json.get('tag'))
        return False

    contents = response_json.get('contents')
    if not isinstance(contents, dict):
        logging.error('response contents is missing or invalid')
        return False

    total = contents.get('foundHttpPostHandlerRequestObjectTotal')
    matches = contents.get('foundHttpPostHandlerRequestObjectMatches')

    if not isinstance(total, int):
        logging.error('invalid foundHttpPostHandlerRequestObjectTotal: %s', total)
        return False
    if not isinstance(matches, list):
        logging.error('invalid foundHttpPostHandlerRequestObjectMatches: %s', matches)
        return False

    for i, match in enumerate(matches, start=1):
        if not isinstance(match, dict):
            logging.error('match #%s is invalid: %s', i, match)
            return False

        post_handler = match.get('foundHttpPostHandlerRequestObjectMatchPostHandler')
        request = match.get('foundHttpPostHandlerRequestObjectMatchLocation')
        url = match.get('foundHttpPostHandlerRequestObjectMatchUrl')

        if post_handler is not None and not is_valid_location(post_handler):
            logging.error('invalid post handler location in match #%s: %s', i, post_handler)
            return False
        if not is_valid_location(request):
            logging.error('invalid request location in match #%s: %s', i, request)
            return False
        if not isinstance(url, str):
            logging.error('invalid url in match #%s: %s', i, url)
            return False

    return True


def log_http_post_handler_request_object_preview(
    response_json: dict[str, typing.Any],
    preview_limit: int = 10,
) -> None:
    contents = response_json['contents']
    total = contents['foundHttpPostHandlerRequestObjectTotal']
    matches = contents['foundHttpPostHandlerRequestObjectMatches']

    logging.info('[ test ] total post-handler request objects: %s', total)

    if not matches:
        logging.info('[ test ] no http post handler request objects matched')
        return

    logging.info('[ test ] showing first %s matches:', min(preview_limit, len(matches)))
    for i, match in enumerate(matches[:preview_limit], start=1):
        url = match.get('foundHttpPostHandlerRequestObjectMatchUrl', '<missing url>')
        post_handler = match.get('foundHttpPostHandlerRequestObjectMatchPostHandler', {})
        request = match.get('foundHttpPostHandlerRequestObjectMatchLocation', {})
        post_handler_file = post_handler.get('filename', '<missing in this kbapi version>')
        request_file = request.get('filename', '<unknown file>')
        logging.info(
            '  #%s url=%s post_handler_file=%s request_file=%s',
            i,
            url,
            post_handler_file,
            request_file,
        )


def run_query(kb_filename: str, query: dict[str, typing.Any]) -> typing.Optional[dict[str, typing.Any]]:
    params = {'kb_location': kb_filename}

    try:
        with requests.post(
            QUERYENGINE_API_URL,
            params=params,
            json=query,
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
    if not (const_strings_response := run_query(parsed_args.use_kb, CONST_STRINGS_MATCHING_QUERY)):
        return 1

    if not valid_const_strings_response(const_strings_response):
        return 1

    log_const_strings_preview(const_strings_response)

    logging.info('[ test ] sending HttpPostHandlerRequestObject query')
    if not (post_handler_response := run_query(parsed_args.use_kb, HTTP_POST_HANDLER_REQUEST_OBJECT_QUERY)):
        return 1

    if not valid_http_post_handler_request_object_response(post_handler_response):
        return 1

    log_http_post_handler_request_object_preview(post_handler_response)

    with parsed_args.save_sarif_to.open('w', encoding='utf-8') as fl:
        json.dump(
            {
                'constStringsMatching': const_strings_response,
                'httpPostHandlerRequestObject': post_handler_response,
            },
            fl,
        )

    logging.info('[ test ] responses are valid and saved to %s', parsed_args.save_sarif_to)
    return 0


if __name__ == '__main__':
    if args := Argparse.run():
        raise SystemExit(main(args))
