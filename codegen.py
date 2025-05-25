import json
import requests


TO_CODEGEN_URL = 'http://codegen:3000/codegen'

def codegen(dhscanner_asts):

    callables = []
    for ast in dhscanner_asts:
        response = requests.post(TO_CODEGEN_URL, json=ast)
        more_callables = json.loads(response.text)['actualCallables']
        # logging.info(more_callables)
        callables.extend(more_callables)

    return callables
