import re
import json
import requests


TO_QUERY_ENGINE_URL = 'http://queryengine:5000/check'

def compute_line_byte_offsets(code: str) -> dict[int, int]:
    offsets = {}
    current_offset = 0
    for i, line in enumerate(code.splitlines(keepends=True)):
        offsets[i + 1] = current_offset
        current_offset += len(line.encode('utf-8'))
    return offsets

def remove_tmp_prefix(filename: str) -> str:
    return re.sub(r"^/tmp/tmp[^/]+/", "", filename)

# pylint: disable=consider-using-with,logging-fstring-interpolation
def query_engine(kb_filename: str, queries_filename: str, debug: bool) -> str:

    kb_and_queries = {
        'kb': ('kb', open(kb_filename, encoding='utf-8')),
        'queries': ('queries', open(queries_filename, encoding='utf-8')),
    }

    url = f'{TO_QUERY_ENGINE_URL}'
    response = requests.post(url, files=kb_and_queries, data={'debug': json.dumps(debug)})
    return response.text
