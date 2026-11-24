#!/usr/bin/env python3
"""Fetch pinned local routing tools; no system Java installation or CAD upload.

Freerouting's 2.5.0 native macOS binary crashes on ComponentOutline serialization
for this board. Use the verified JVM release and a local Temurin runtime instead.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import tarfile
from urllib.request import urlretrieve


JAR = ('https://github.com/freerouting/freerouting/releases/download/v2.5.0/freerouting-2.5.0.jar',
       'f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7')
JRE = ('https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/'
       'OpenJDK25U-jre_x64_mac_hotspot_25.0.5_8.tar.gz',
       '806902c796c670969b7b27df73b8f0fe0924a61bd65083aa53064115e49cab2d')


def safe_members(archive, destination):
    members = archive.getmembers()
    base = destination.resolve()
    for member in members:
        target = (base / member.name).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f'Unsafe archive member: {member.name}')
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError(f'Unsupported archive member: {member.name}')
        if member.issym() or member.islnk():
            link = ((target.parent if member.issym() else base) / member.linkname).resolve()
            if base not in link.parents:
                raise ValueError(f'Unsafe archive link: {member.name}')
    return members


def fetch(output, asset):
    url, expected = asset
    path = output / url.rsplit('/', 1)[1]
    if not path.exists():
        urlretrieve(url, path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f'Checksum mismatch: {path}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'build/routing-tools')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64':
        parser.error('Pinned local runtime is macOS x64; supply your own Java 25+ on other platforms')
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jar, archive = list(pool.map(lambda asset: fetch(output, asset), [JAR, JRE]))
    java = output / 'jdk-25.0.5+8-jre/Contents/Home/bin/java'
    if not java.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(output, members=safe_members(tar, output))
    (output / 'jvm-router-provenance.json').write_text(json.dumps({
        'freerouting_version': '2.5.0', 'jar_url': JAR[0], 'jar_sha256': JAR[1],
        'java_release': 'Temurin 25.0.5+8 JRE', 'jre_url': JRE[0], 'jre_sha256': JRE[1],
    }, indent=2)+'\n')
    print('Java:', java)
    print('Router:', jar)


if __name__ == '__main__':
    main()
