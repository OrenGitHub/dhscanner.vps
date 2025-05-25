BASEDIR: typing.Final[pathlib.Path] = Path('/tmp/dhscanner_jobs')

def mk_jobdir_if_needed(job_id: str) -> pathlib.Path:
    job_dir = BASEDIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def get_unique_id() -> str:
    return str(uuid.uuid4())

def get_suffix_from(filename: str) -> str:
    return Path(filename).suffix or '.unknown'

def mk_stored_filename(job_dir: pathlib.Path, suffix: str) -> pathlib.Path:
    unique_id = get_unique_id()
    return job_dir / f'{unique_id}{suffix}'

def store_file(content: AsyncIterator[bytes], original_filename_in_repo: str, job_id: str) -> None:
    job_dir = mk_jobdir_if_needed(job_id)
    suffix = get_suffix_from(original_filename_in_repo)
    stored_filename = mk_stored_filename(job_dir, suffix)
    store_content_as_file_on_disk(content, stored_filename, original_filename_in_repo, suffix)
    map_stored_filname_to_original(stored_filename, original_filename_in_repo, suffix, job_id)

def store_content_as_file_on_disk(
    content: AsyncIterator[bytes],
    stored_filename: pathlib.Path,
    original_filename_in_repo: str,
    suffix: str
) -> None:

    dest = job_dir / f'{unique_id}{suffix}'
    with open(dest, "wb") as fl:
        async for chunk in content:
            fl.write(chunk)
