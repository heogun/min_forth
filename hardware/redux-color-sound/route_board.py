#!/usr/bin/env python3
"""Local DSN/SES routing bridge; run using KiCad's bundled Python.

The project PCB is never written here: prepare/import operate on a separate work tree.
Existing copper/placements are locked before export and audited after import.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from check_kicad import HERE, PROJECT
from routing_checks import preservation_report


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(board):
    copper = {}
    for item in board.GetTracks():
        record = {'type': item.GetClass(), 'net': item.GetNetname(),
                  'layer': item.GetLayer(),
                  'width': item.GetWidth(item.TopLayer()) if item.GetClass() == 'PCB_VIA' else item.GetWidth(),
                  'start': [item.GetStart().x, item.GetStart().y],
                  'end': [item.GetEnd().x, item.GetEnd().y], 'locked': item.IsLocked()}
        if item.GetClass() == 'PCB_VIA':
            record['drill'] = item.GetDrillValue()
        copper[item.m_Uuid.AsString()] = record
    footprints = {f.GetReference(): {'uuid': f.m_Uuid.AsString(),
        'position': [f.GetPosition().x, f.GetPosition().y],
        'angle': f.GetOrientationDegrees(), 'locked': f.IsLocked(),
        'pads': {p.GetNumber(): [p.GetPosition().x, p.GetPosition().y, p.GetNetname()]
                 for p in f.Pads()}}
        for f in board.GetFootprints()}
    return {'copper': copper, 'footprints': footprints}


def prepare(pcbnew, source, work):
    if work.exists():
        raise ValueError(f'Refusing to overwrite routing work directory: {work}')
    work.mkdir(parents=True)
    original = source / f'{PROJECT}.kicad_pcb'
    shutil.copy2(original, work / 'before.kicad_pcb')
    shutil.copy2(source / f'{PROJECT}.kicad_pro', work / 'before.kicad_pro')
    board = pcbnew.LoadBoard(str(work / 'before.kicad_pcb'))
    before = snapshot(board)
    before['source_sha256'] = digest(original)
    before['source'] = str(original)
    (work / 'before.json').write_text(json.dumps(before, indent=2)+'\n')
    # The GND pour follows the whole (possibly non-rectangular) board outline.
    outline = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outline, False) or outline.OutlineCount() != 1:
        raise ValueError('Board outline must be one closed polygon')
    expanded = 0
    for zone in board.Zones():
        if zone.GetNetname() != 'GND' or zone.Outline().OutlineCount() != 1:
            continue
        # Rebuild the zone's own polygon in place; handing KiCad a temporary
        # SHAPE_POLY_SET via SetOutline() crashes the 10.0 Python bindings.
        points = [(p.x, p.y) for p in outline.COutline(0).CPoints()]
        polygon = zone.Outline()
        polygon.RemoveAllContours()
        polygon.NewOutline()
        for x, y in points:
            polygon.Append(x, y)
        expanded += 1
    assert expanded == 1, 'Expected exactly one existing multilayer GND zone'
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    for track in board.GetTracks():
        track.SetLocked(True)
    for footprint in board.GetFootprints():
        footprint.SetLocked(True)
    pcbnew.SaveBoard(str(work / 'locked.kicad_pcb'), board)
    if not pcbnew.ExportSpecctraDSN(board, str(work / 'route.dsn')):
        raise RuntimeError('DSN export failed')
    text = (work / 'route.dsn').read_text()
    assert '(type fix)' in text, 'No locked copper exported'
    print(f'Exported {len(before["copper"])} locked copper items; GND zone follows the board outline.')
    print(f'Input for local router: {work / "route.dsn"}')


def import_session(pcbnew, source, work):
    before = json.loads((work / 'before.json').read_text())
    if digest(source / f'{PROJECT}.kicad_pcb') != before['source_sha256']:
        raise ValueError('Source PCB changed since export; refusing stale routing import')
    board = pcbnew.LoadBoard(str(work / 'locked.kicad_pcb'))
    if not pcbnew.ImportSpecctraSES(board, str(work / 'route.ses')):
        raise RuntimeError('SES import failed')
    # DSN uses a 0.1um grid. Do not let its rounding move original footprints.
    for footprint in board.GetFootprints():
        original = before['footprints'][footprint.GetReference()]
        footprint.SetOrientationDegrees(original['angle'])
        footprint.SetPosition(pcbnew.VECTOR2I(*original['position']))
    after = snapshot(board)
    old_ids = set(before['copper'])
    preserved = old_ids & set(after['copper'])
    report = {'original_copper_count': len(old_ids), 'same_uuid_after_import': len(preserved),
              'imported_copper_count': len(after['copper']),
              'missing_original_ids': sorted(old_ids-set(after['copper']))}
    changed = []
    for key in preserved:
        a, b = dict(before['copper'][key]), dict(after['copper'][key])
        a.pop('locked'); b.pop('locked')
        if a != b:
            changed.append(key)
    report['changed_original_ids'] = changed
    fp_changed = []
    for ref, old in before['footprints'].items():
        a, b = dict(old), dict(after['footprints'][ref])
        a.pop('locked'); b.pop('locked')
        if a != b:
            fp_changed.append(ref)
    report['changed_footprints'] = fp_changed
    # Restore each pre-existing lock state; new routes remain editable.
    for track in board.GetTracks():
        key = track.m_Uuid.AsString()
        track.SetLocked(before['copper'][key]['locked'] if key in before['copper'] else False)
    for fp in board.GetFootprints():
        fp.SetLocked(before['footprints'][fp.GetReference()]['locked'])
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    candidate = work / 'candidate'
    shutil.copytree(source, candidate)
    pcbnew.SaveBoard(str(candidate / f'{PROJECT}.kicad_pcb'), board)
    (work / 'import-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=2))
    print('Changed original copper:', len(changed), 'changed placements:', fp_changed)
    print('Candidate:', candidate)


def adopt(source, work):
    before = json.loads((work / 'before.json').read_text())
    original = source / f'{PROJECT}.kicad_pcb'
    candidate = work / 'candidate' / f'{PROJECT}.kicad_pcb'
    if digest(original) != before['source_sha256']:
        raise ValueError('Source PCB changed; refusing to overwrite user work')
    checked = work / 'checked'
    summary = json.loads((checked / 'summary.json').read_text())
    if summary['source_sha256'][candidate.name] != digest(candidate):
        raise ValueError('Candidate changed after DRC; run the checker again')
    erc = json.loads((checked / 'erc.json').read_text())
    drc = json.loads((checked / 'drc.json').read_text())
    if any(sheet['violations'] for sheet in erc['sheets']):
        raise ValueError('ERC findings remain')
    if any(drc[key] for key in ('violations', 'unconnected_items', 'schematic_parity')):
        raise ValueError('DRC, exclusions, unconnected items, or schematic mismatch remain')
    protected = preservation_report((work / 'before.kicad_pcb').read_text(), candidate.read_text())
    if not protected['preserved']:
        raise ValueError(f'Protected copper or placements changed: {protected}')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=HERE,
                            capture_output=True, text=True, check=True).stdout.strip()
    relative = original.relative_to(HERE.parents[1]).as_posix()
    committed_source = subprocess.run(['git', 'show', commit+':'+relative], cwd=HERE,
                                     capture_output=True, check=True).stdout
    if hashlib.sha256(committed_source).hexdigest() != before['source_sha256']:
        raise ValueError('Source snapshot has no matching committed PCB for reproducible protection proof')
    shutil.copy2(candidate, original)
    report = {'status': 'ROUTED DRAFT - TIMING/HARDWARE UNVERIFIED',
              'source_commit': commit, 'source_sha256': before['source_sha256'],
              'pcb_sha256': digest(original), 'kicad_version': summary['kicad_version'],
              'freerouting_version': '2.5.0 JVM', 'protection': protected,
              'checks': {'erc': 0, 'physical_drc': 0, 'schematic_parity': 0,
                         'unconnected_items': 0, 'excluded_findings': 0},
              'ground_zone': 'board outline',
              'remaining_validation': ['worst-case timing', 'clock waveform/fanout',
                  'power/current/thermal budget', 'real hardware tests']}
    (source / 'routing-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Adopted zero-DRC candidate; all original copper and footprints preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'import', 'adopt'])
    parser.add_argument('--project', type=Path, default=HERE / 'integrated')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    source, work = args.project.resolve(), args.work.resolve()
    if source == work or source in work.parents or work in source.parents:
        parser.error('Project and work directories must not contain each other')
    if args.action == 'adopt':
        adopt(source, work)
        return
    import wx
    app = wx.App(False)
    import pcbnew
    if args.action == 'prepare':
        prepare(pcbnew, source, work)
    else:
        import_session(pcbnew, source, work)
    del app


if __name__ == '__main__':
    main()
