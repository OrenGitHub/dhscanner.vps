import typing
from language import Language

AST_BUILDER_URL = {
    Language.JS: 'http://frontjs:3000/to/esprima/js/ast',
    Language.TS: 'http://frontts:3000/to/native/ts/ast',
    Language.TSX: 'http://frontts:3000/to/native/ts/ast',
    Language.PHP: 'http://frontphp:5000/to/php/ast',
    Language.PY: 'http://frontpy:5000/to/native/py/ast',
    Language.RB: 'http://frontrb:3000/to/native/cruby/ast',
    Language.CS: 'http://frontcs:8080/to/native/cs/ast',
    Language.GO: 'http://frontgo:8080/to/native/go/ast',
    Language.BLADE_PHP: 'http://frontphp:5000/to/php/code'
}

CSRF_TOKEN = 'http://frontphp:5000/csrf_token'

def read_single_file(filename: str, offsets: typing.Optional[dict[str, dict[int, int]]] = None):

    with open(filename, 'r', encoding='utf-8') as fl:
        code = fl.read()

    if offsets is not None:
        cleaned = remove_tmp_prefix(filename)
        offsets[cleaned] = compute_line_byte_offsets(code)

    return { 'source': (filename, code) }

# TODO: adjust other reasons for exclusion
# the reasons might depend on the language
# (like the third party directory name: node_module for javascript,
# site-packages for python or vendor/bundle for ruby etc.)
# pylint: disable=unused-argument
def scan_this_file(filename: str, language: Language, ignore_testing_code: bool = False) -> bool:
    if ignore_testing_code and '/test/' in filename:
        return False

    if ignore_testing_code and '.test.' in filename:
        return False

    return True

# Laravel has a built-in csrf token demand
# There are other options too, but currently
# I'm sticking to Laravel ... this means that all
# the php files should be added using the same session
def add_php_asts(files: dict[Language, list[str]], asts: dict) -> None:

    session = requests.Session()
    response = session.get(CSRF_TOKEN)
    token = response.text
    cookies = session.cookies
    headers = { 'X-CSRF-TOKEN': token }

    filenames = files[Language.PHP]
    for filename in filenames:
        if filename in files[Language.BLADE_PHP]:
            just_one_blade_php_file = read_single_file(filename)

            # sometimes blade.php files are just plain php files
            # this could happen for various reasons ...
            # try the normal php parser first
            response = session.post(
                AST_BUILDER_URL[Language.PHP],
                files=just_one_blade_php_file,
                headers=headers,
                cookies=cookies
            )

            if response.ok:
                # no transformations need to be done
                # TODO: fix multiple sends of such blade.php files
                php_source_code = just_one_blade_php_file
            else:
                response = session.post(
                    AST_BUILDER_URL[Language.BLADE_PHP],
                    files=just_one_blade_php_file,
                    headers=headers,
                    cookies=cookies
                )
                php_source_code = { 'source': (filename, response.text) }
        else:
            php_source_code = read_single_file(filename)

        # from here on, plain php code
        response = session.post(
            AST_BUILDER_URL[Language.PHP],
            files=php_source_code,
            headers=headers,
            cookies=cookies
        )

        asts[Language.PHP].append({
            'filename': filename,
            'actual_ast': response.text
        })


def add_ast(filename: str, language: Language, asts: dict, offsets: dict[str, dict[int, int]]) -> None:

    one_file_at_a_time = read_single_file(filename, offsets)
    response = requests.post(AST_BUILDER_URL[language], files=one_file_at_a_time)
    asts[language].append({ 'filename': filename, 'actual_ast': response.text })

def parse_code(files: dict[Language, list[str]], offsets: dict[str, dict[int, int]]) -> dict[Language, list[dict[str, str]]]:

    asts = collections.defaultdict(list) # type: ignore[var-annotated]

    for language, filenames in files.items():
        if language not in [Language.PHP, Language.BLADE_PHP]:
            for filename in filenames:
                add_ast(filename, language, asts, offsets)

    # separately because php chosen webserver
    # has a more complex sessio mechanism
    # see more details inside the function
    # it handles both plain php files and blade.php files
    add_php_asts(files, asts)

    return asts