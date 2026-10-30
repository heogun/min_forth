#!/usr/bin/env python3
"""Audit a copy of Redux CAD without changing CAD or global KiCad settings."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAC_CLI = Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
MAC_FOOTPRINTS = MAC_CLI.parent.parent / 'SharedSupport/footprints'
PROJECT = '8-Bit CPU 32k'


def find_cli(explicit=None):
    candidate = explicit or shutil.which('kicad-cli')
    if not candidate and MAC_CLI.is_file():
        candidate = str(MAC_CLI)
    if not candidate:
        raise ValueError('kicad-cli not found; supply --cli')
    resolved = shutil.which(str(candidate))
    if not resolved:
        raise ValueError(f'KiCad CLI is not executable: {candidate}')
    return Path(resolved).resolve()


def add_footprint_libraries(project, installed):
    """Keep custom libraries and add installed libraries only to the copy."""
    libraries = sorted(installed.glob('*.pretty'))
    if not libraries:
        raise ValueError(f'No *.pretty footprint libraries in {installed}')
    table = project / 'fp-lib-table'
    text = table.read_text() if table.exists() else '(fp_lib_table\n)\n'
    names = set(re.findall(r'\(name\s+"([^"]+)"\)', text))
    additions = []
    for library in libraries:
        if library.stem not in names:
            name = json.dumps(library.stem)
            uri = json.dumps(library.resolve().as_posix())
            additions.append(
                f'  (lib (name {name})(type "KiCad")(uri {uri})'
                '(options "")(descr ""))\n'
            )
    end = text.rfind(')')
    if end < 0:
        raise ValueError(f'Invalid library table: {table}')
    table.write_text(text[:end] + ''.join(additions) + text[end:])
    return len(additions)


def summarize(report, kind):
    if kind == 'erc':
        sections = {'violations': [v for s in report['sheets'] for v in s['violations']]}
    else:
        sections = {key: report[key] for key in
                    ('violations', 'unconnected_items', 'schematic_parity')}
    result = {}
    for name, violations in sections.items():
        counts = Counter()
        for item in violations:
            state = 'excluded' if item.get('excluded', False) else 'active'
            counts[(state, item['severity'], item['type'])] += 1
        result[name] = [
            {'state': state, 'severity': severity, 'type': typ, 'count': count}
            for (state, severity, typ), count in sorted(counts.items())
        ]
    return result


def fingerprint(directory):
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob('*')) if p.is_file()
    }


def run_check(cli, project, output, kind, env):
    extension = 'kicad_sch' if kind == 'erc' else 'kicad_pcb'
    domain = 'sch' if kind == 'erc' else 'pcb'
    command = [str(cli), domain, kind, '--format', 'json', '--severity-all',
               '--exit-code-violations', '--output', str(output / f'{kind}.json')]
    if kind == 'drc':
        command.append('--schematic-parity')
    command.append(str(project / f'{PROJECT}.{extension}'))
    completed = subprocess.run(command, capture_output=True, text=True, env=env)
    (output / f'{kind}.log').write_text(completed.stdout + completed.stderr)
    if completed.returncode not in (0, 5):
        raise RuntimeError(f'{kind} failed ({completed.returncode}); see {output / (kind + ".log")}')
    report = json.loads((output / f'{kind}.json').read_text())
    summary = summarize(report, kind)
    # Never treat a nonzero violation exit as a successful audit.
    active = sum(row['count'] for rows in summary.values() for row in rows
                 if row['state'] == 'active')
    return {'exit_code': completed.returncode, 'active_findings': active, 'sections': summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', help='KiCad CLI executable (auto-detected on macOS)')
    parser.add_argument('--footprints', type=Path, help='Installed *.pretty library directory')
    parser.add_argument('--source', type=Path,
                        default=ROOT / 'minimal64/Revision 1.4 Redux/KiCAD9')
    parser.add_argument('--out', type=Path, default=HERE / 'build/kicad-baseline')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.out.resolve()
    if output == source or source in output.parents or output in source.parents:
        parser.error('--out and --source must not contain each other')
    try:
        cli = find_cli(args.cli)
        footprint_option = args.footprints or os.environ.get('KICAD10_FOOTPRINT_DIR')
        footprints = Path(footprint_option).resolve() if footprint_option else MAC_FOOTPRINTS
        for extension in ('kicad_sch', 'kicad_pcb', 'kicad_pro'):
            if not (source / f'{PROJECT}.{extension}').is_file():
                raise ValueError(f'Missing {PROJECT}.{extension} in {source}')
        before = fingerprint(source)
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cad-copy-', dir=output) as temp:
            temp = Path(temp)
            project = temp / 'source'
            shutil.copytree(source, project)
            added = add_footprint_libraries(project, footprints)
            env = dict(os.environ, KICAD_CONFIG_HOME=str(temp / 'config'))
            version = subprocess.run([str(cli), 'version'], check=True,
                                     capture_output=True, text=True, env=env).stdout.strip()
            summary = {'kicad_version': version, 'source': str(source),
                       'source_sha256': before, 'added_footprint_libraries': added,
                       'checks': {kind: run_check(cli, project, output, kind, env)
                                  for kind in ('erc', 'drc')}}
        if fingerprint(source) != before:
            raise RuntimeError('Source CAD changed while auditing; result is not a stable baseline')
        summary['source_unchanged'] = True
        (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        for kind, check in summary['checks'].items():
            print(f'{kind.upper()}: {check["active_findings"]} active findings '
                  f'(KiCad exit {check["exit_code"]})')
        print(f'Reports: {output}')
        return int(any(c['exit_code'] or c['active_findings']
                       for c in summary['checks'].values()))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(2, f'Audit failed: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
