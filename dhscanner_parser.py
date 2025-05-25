from language import Language

DHSCANNER_AST_BUILDER_URL = {
    Language.JS: 'http://parsers:3000/from/js/to/dhscanner/ast',
    Language.TS: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.TSX: 'http://parsers:3000/from/ts/to/dhscanner/ast',
    Language.PHP: 'http://parsers:3000/from/php/to/dhscanner/ast',
    Language.PY: 'http://parsers:3000/from/py/to/dhscanner/ast',
    Language.RB: 'http://parsers:3000/from/rb/to/dhscanner/ast',
    Language.CS: 'http://parsers:3000/from/cs/to/dhscanner/ast',
    Language.GO: 'http://parsers:3000/from/go/to/dhscanner/ast',
}

def add_dhscanner_ast(filename: str, language: Language, code, asts) -> None:

    content = { 'filename': filename, 'content': code}
    url = DHSCANNER_AST_BUILDER_URL[language]
    response = requests.post(f'{url}?filename={filename}', json=content)
    asts[language].append({ 'filename': filename, 'dhscanner_ast': response.text })

def parse_language_asts(language_asts):

    dhscanner_asts = collections.defaultdict(list)

    for language, asts in language_asts.items():
        for ast in asts:
            add_dhscanner_ast(ast['filename'], language, ast['actual_ast'], dhscanner_asts)

    return dhscanner_asts