#!/usr/bin/env python3
"""Build verifiable installer assets from unmodified official XrayR releases."""
import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://github.com/XrayR-project/XrayR/releases/download/v0.9.4/'
HASHES = {
    'XrayR-linux-64.zip': 'ad06efe7ca3c19ea20817fb2aa163185f012433d97f8d4cc30eff30ca02bc5b4',
    'XrayR-linux-arm64-v8a.zip': '2c2fa9dbc282f30caecaa026319927f6f0a4492f576239fa59c490abd2076558',
    'XrayR-v0.9.4-source.tar.gz': '49319851bc06889d30c9004d405080caaa52d456b8ec9efc394b2ba848614ef0',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def fetch(url, target):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'hainiu6-xrayr-release'})
            with urllib.request.urlopen(req, timeout=180) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def smoke_test(zip_path):
    """A missing config must reach the config reader, never panel initialization."""
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        print('Linux binary smoke test skipped on this host.', flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='xrayr-cli-') as td:
        directory = Path(td)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extract('XrayR', directory)
        executable = directory / 'XrayR'
        executable.chmod(0o755)
        missing_config = directory / 'deliberately-missing.yml'
        result = subprocess.run([str(executable), '--config', str(missing_config)],
                                capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if result.returncode == 0 or 'Config file error' not in output or 'unknown command' in output:
            raise RuntimeError('Real binary failed --config argument regression check.')
    print('Real Linux binary --config regression passed.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=ROOT / 'build' / 'upstream')
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    tag = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise RuntimeError('VERSION must be vMAJOR.MINOR.PATCH.')
    script = (ROOT / 'install-xrayr.sh').read_text()
    if '/releases/download/' + tag not in script:
        raise RuntimeError('Installer release URL must match VERSION.')

    def download_asset(name):
        cached = args.cache / name
        url = (UPSTREAM + name) if name.endswith('.zip') else 'https://api.github.com/repos/XrayR-project/XrayR/tarball/v0.9.4'
        if not cached.is_file() or digest(cached) != HASHES[name]:
            fetch(url, cached)
        if digest(cached) != HASHES[name]:
            raise RuntimeError('Upstream checksum mismatch: ' + name)
        shutil.copyfile(cached, args.out / name)
        print('Verified upstream:', name, flush=True)
        if name.endswith('.zip'):
            checksum = args.cache / (name + '.dgst')
            if not checksum.is_file():
                fetch(UPSTREAM + name + '.dgst', checksum)
            match = re.search(r'SHA2-256=\s*([0-9a-f]+)', checksum.read_text())
            if not match or match.group(1) != HASHES[name]:
                raise RuntimeError('Upstream .dgst mismatch: ' + name)
            shutil.copyfile(checksum, args.out / checksum.name)
            with zipfile.ZipFile(cached) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError('Invalid ZIP: ' + name)
                binary = archive.read('XrayR')
                expected_arch = 62 if name == 'XrayR-linux-64.zip' else 183
                if binary[:4] != b'\x7fELF' or int.from_bytes(binary[18:20], 'little') != expected_arch:
                    raise RuntimeError('Wrong binary architecture: ' + name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download_asset, HASHES))
    smoke_test(args.out / 'XrayR-linux-64.zip')
    for name in ['install-xrayr.sh', 'README.md', 'LICENSE', 'NOTICE.md', 'VERSION']:
        shutil.copyfile(ROOT / name, args.out / name)
    package_names = sorted(list(HASHES) + [n + '.dgst' for n in HASHES if n.endswith('.zip')]
                           + ['install-xrayr.sh', 'README.md', 'LICENSE', 'NOTICE.md', 'VERSION'])
    bundle = args.out / 'xrayr-native-installer.tar.gz'
    with bundle.open('wb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as gz:
            with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for name in package_names:
                    data = (args.out / name).read_bytes()
                    info = tarfile.TarInfo('xrayr-native-installer/' + name)
                    info.size = len(data)
                    info.mode = 0o755 if name.endswith('.sh') else 0o644
                    tar.addfile(info, io.BytesIO(data))
    all_names = sorted(package_names + [bundle.name])
    (args.out / 'SHA256SUMS-XrayR.txt').write_text(
        ''.join(digest(args.out / name) + '  ' + name + '\n' for name in all_names))
    print(json.dumps({'version': tag, 'assets': all_names, 'bundle_bytes': bundle.stat().st_size}), flush=True)


if __name__ == '__main__':
    main()
