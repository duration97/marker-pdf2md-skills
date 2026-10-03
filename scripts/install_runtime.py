"""Explicit, checksum-verified download of optional Windows x64 Vulkan runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile

URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b11344/llama-b11344-bin-win-vulkan-x64.zip'
SHA256 = 'f561d5af233f802bd0605ff281fd204fba162dfaf09032a361e244ad292ba397'
REQUIRED = ('llama-server.exe', 'llama-server-impl.dll', 'llama.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-vulkan.dll')


def validate_members(archive):
    members = archive.infolist()
    if len(members) > 2000 or sum(m.file_size for m in members) > 500 * 1024**2:
        raise ValueError('Archive exceeds runtime extraction limits')
    for member in members:
        name = member.filename.replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError('Unsafe archive member: ' + name)
    return members


def locate_runtime(root):
    binaries = list(root.rglob('llama-server.exe')) if root.exists() else []
    valid = [p for p in binaries if all((p.parent / name).is_file() for name in REQUIRED)]
    if len(valid) != 1:
        raise ValueError('Expected one complete runtime, found ' + str(len(valid)))
    return valid[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path(__file__).resolve().parent.parent / 'runtime' / 'llama-vulkan')
    parser.add_argument('--check', action='store_true', help='Inspect existing runtime; no network or execution')
    args = parser.parse_args()
    target = args.destination.expanduser().resolve()
    if args.check:
        print(locate_runtime(target))
        return
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('This installer supports Windows x64 only; use an official platform build and --llama-server elsewhere')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Destination already contains files; preserve it and choose a new destination')
    target.parent.mkdir(parents=True, exist_ok=True)
    # A private staging directory prevents exposing a partial or unverified binary.
    with tempfile.TemporaryDirectory(prefix='llama-download-', dir=target.parent) as temp:
        stage = Path(temp)
        archive_path = stage / 'runtime.zip'
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(URL, timeout=60) as response, archive_path.open('wb') as output:
            while True:
                chunk = response.read(1024**2)
                if not chunk:
                    break
                size += len(chunk)
                if size > 200 * 1024**2:
                    raise ValueError('Download exceeds runtime size limit')
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError('SHA-256 mismatch; downloaded binary will not be installed')
        extracted = stage / 'extracted'
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            validate_members(archive)
            archive.extractall(extracted)
        binary = locate_runtime(extracted)
        relative = binary.relative_to(extracted)
        (extracted / 'source.json').write_text(json.dumps({'url': URL, 'sha256': SHA256}, indent=2), encoding='utf-8')
        # The full vendor bundle is retained, including backend DLLs and licenses.
        if target.exists():
            target.rmdir()  # only the previously checked empty directory
        shutil.move(str(extracted), str(target))
        print(target / relative)


if __name__ == '__main__':
    main()
