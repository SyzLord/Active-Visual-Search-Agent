"""Restore the two older source PDFs directly from the public archives."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from urllib.parse import urldefrag, urlsplit

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'outputs' / '页底印章年份复读_2026-11-18_晚间'
SOURCES = (
    (STUDY, 'cowell', 'original'),
    (STUDY / 'reserve', 'tweed', 'source_file'),
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


for directory, source, field in SOURCES:
    item = json.loads((directory / 'holdout.json').read_text())['sources'][source]
    dest = directory / item[field]
    expected = item['original_sha256']
    if dest.exists():
        if digest(dest) != expected:
            raise SystemExit(f'Checksum mismatch for existing file: {dest}')
        print(f'Verified {dest.relative_to(ROOT)}')
        continue

    url = urldefrag(item['source']).url
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'www.justice.gov', 'www.archives.gov'}:
        raise SystemExit(f'Unexpected archive URL: {url}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    incoming = dest.with_name(dest.name + '.part')
    if not incoming.exists() or digest(incoming) != expected:
        subprocess.run(
            ['curl', '--fail', '--silent', '--show-error', '--location',
             '--continue-at', '-', '--connect-timeout', '20', '--max-time', '1800',
             url, '--output', str(incoming)],
            check=True,
        )
    if digest(incoming) != expected:
        raise SystemExit(f'Archive checksum mismatch for {source}. Remove {incoming} before retrying.')
    incoming.replace(dest)
    print(f'Downloaded and verified {dest.relative_to(ROOT)}')
