#!/usr/bin/env python3
"""Populate the integrated PCB draft from the exported schematic netlist.

Run with KiCad's bundled Python. This is placement/net synchronization, NOT routing.
Only copper on explicitly split legacy nets is removed. No CPU clock is rerouted.
"""

import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from cad_sexpr import parse, quoted, replace
from check_kicad import HERE, PROJECT


def sync_fields(path, components):
    text = path.read_text()
    root = parse(text)
    edits = []
    for fp in root.nodes('footprint'):
        props = {p.value(): p for p in fp.nodes('property')}
        ref = props['Reference'].value(2)
        if ref not in components:
            continue
        for key in ('Description', 'Datasheet'):
            field = components[ref].find(f'./fields/field[@name="{key}"]')
            value = (field.text or '') if field is not None else ''
            if key in props:
                edits.append(quoted(props[key].children[2], value))
            else:
                edits.append((fp.end-1, fp.end-1,
                    f'(property "{key}" {json.dumps(value)} (at 0 0 0) '
                    '(layer "F.Fab") (effects (font (size 1 1)) (hide yes)))\n'))
    path.write_text(replace(text, edits))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=HERE / 'integrated')
    args = parser.parse_args()
    project = args.project.resolve()
    manifest = json.loads((project / 'extension-manifest.json').read_text())
    if (project / 'placement-report.json').exists():
        parser.error('Placement was already applied; refusing to overwrite routed/user work')
    import wx
    app = wx.App(False)
    import pcbnew
    board_path = project / f'{PROJECT}.kicad_pcb'
    board = pcbnew.LoadBoard(str(board_path))
    root = ET.parse(project / 'integrated.net.xml').getroot()
    components = {c.get('ref'): c for c in root.findall('./components/comp')}
    pin_nets = {}
    for net in root.findall('./nets/net'):
        for node in net.findall('node'):
            pin_nets[(node.get('ref'), node.get('pin'))] = net.get('name')
    footprints = {f.GetReference(): f for f in board.GetFootprints()}
    old_tracks = list(board.GetTracks())
    old_track_count = len(old_tracks)
    net_names = {}
    for ref, fp in footprints.items():
        for pad in fp.Pads():
            target = pin_nets.get((ref, pad.GetNumber()))
            if target is not None:
                net_names.setdefault(pad.GetNetCode(), set()).add(target)
    removed = []
    split = {code for code, names in net_names.items() if len(names) > 1}
    for track in old_tracks:
        if track.GetNetCode() in split:
            removed.append({'uuid': track.m_Uuid.AsString(), 'net': track.GetNetname()})
            board.Remove(track)
    # Relabel unsplit nets in place, preserving their copper and all net codes.
    for code, names in net_names.items():
        if len(names) == 1 and code:
            board.FindNet(code).SetNetname(next(iter(names)))
    nets = {n.GetNetname(): n for n in board.GetNetsByNetcode().values()}
    for name in sorted(set(pin_nets.values())):
        if name not in nets:
            net = pcbnew.NETINFO_ITEM(board, name)
            board.Add(net)
            nets[name] = net
    plugin = pcbnew.PCB_IO_KICAD_SEXPR()
    standard = Path(os.environ.get('KICAD10_FOOTPRINT_DIR',
        '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints'))
    new_refs = {p['ref'] for p in manifest['parts']}
    for part in manifest['parts']:
        ref = part['ref']
        if ref in footprints:
            raise ValueError(f'New reference collides with baseline: {ref}')
        library, name = part['footprint'].split(':')
        library_path = project / (library + '.pretty')
        if not library_path.is_dir():
            library_path = standard / (library + '.pretty')
        fp = plugin.FootprintLoad(str(library_path), name, False)
        if fp is None:
            raise ValueError(f'Missing footprint: {part["footprint"]}')
        fp.SetFPIDAsString(part['footprint'])
        fp.SetReference(ref)
        fp.SetValue(part['value'])
        fp.Value().SetVisible(False)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.8), pcbnew.FromMM(0.8)))
        fp.Reference().SetTextThickness(pcbnew.FromMM(0.12))
        comp = components[ref]
        path = comp.find('sheetpath').get('tstamps') + comp.findtext('tstamps').split()[0]
        fp.SetPath(pcbnew.KIID_PATH(path))
        board.Add(fp)
        footprints[ref] = fp
    for ref, comp in components.items():
        fp = footprints[ref]
        fp.SetValue(comp.findtext('value', ''))
        for pad in fp.Pads():
            name = pin_nets.get((ref, pad.GetNumber()))
            if name is not None:
                pad.SetNet(nets[name])
            elif ref in new_refs:
                pad.SetNetCode(0)
    # Shelf placement is intentionally a reviewable draft, not an optimized layout.
    cursor_x, cursor_y, row_height = 276.0, 64.0, 0.0
    placements = {}
    placed = set()

    def place_group(ref, decoupler=None):
        nonlocal cursor_x, cursor_y, row_height
        fp = footprints[ref]
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        if ref.startswith('U') and ref != 'U76':
            fp.SetOrientationDegrees(90)
        box = fp.GetBoundingBox()
        width = pcbnew.ToMM(box.GetWidth()) + 4
        height = pcbnew.ToMM(box.GetHeight()) + 4
        if decoupler:
            width += 9
        if cursor_x + width > 446:
            cursor_x, cursor_y = 276.0, cursor_y + row_height
            row_height = 0
        if cursor_y + height > 203:
            raise ValueError(f'Placement exceeds draft outline at {ref}; no silent overlap')
        dx = cursor_x+2-pcbnew.ToMM(box.GetX())
        dy = cursor_y+2-pcbnew.ToMM(box.GetY())
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(dx), pcbnew.FromMM(dy)))
        placements[ref] = [dx, dy, fp.GetOrientationDegrees()]
        placed.add(ref)
        if decoupler:
            cap = footprints[decoupler]
            cap.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cursor_x+width-7),
                                          pcbnew.FromMM(cursor_y+height/2)))
            placements[decoupler] = [pcbnew.ToMM(cap.GetPosition().x),
                                     pcbnew.ToMM(cap.GetPosition().y), 0]
            placed.add(decoupler)
        cursor_x += width
        row_height = max(row_height, height)

    for part in manifest['parts']:
        ref = part['ref']
        if ref.startswith('U'):
            place_group(ref, f'C{34+int(ref[1:])-64}')
        elif ref == 'X2':
            place_group(ref, 'C63')
    for part in manifest['parts']:
        if part['ref'] not in placed:
            place_group(part['ref'])
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    max_x = max(max(e.GetStart().x, e.GetEnd().x) for e in edges)
    for edge in edges:
        start, end = edge.GetStart(), edge.GetEnd()
        if start.x == max_x:
            start.x = pcbnew.FromMM(450)
            edge.SetStart(start)
        if end.x == max_x:
            end.x = pcbnew.FromMM(450)
            edge.SetEnd(end)
    note = pcbnew.PCB_TEXT(board)
    note.SetText('COLOR + SN76489 DRAFT / UNROUTED / DO NOT FABRICATE')
    note.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(360), pcbnew.FromMM(57)))
    note.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(1)))
    note.SetTextThickness(pcbnew.FromMM(0.15))
    note.SetLayer(pcbnew.F_SilkS)
    board.Add(note)
    for drawing in board.GetDrawings():
        if isinstance(drawing, pcbnew.PCB_TEXT) and drawing.GetText().startswith('*Supply voltage'):
            drawing.SetText('*Supply: regulated 5.0V +/-5%, single source. Current budget TBD. '
                'UART 500kbps, 7N2, LF. Unlabelled ceramics 100nF. INTEGRATION DRAFT - DO NOT FABRICATE.')
    pcbnew.SaveBoard(str(board_path), board)
    sync_fields(board_path, components)
    report = {'status': 'PLACED / UNROUTED - NOT FOR FABRICATION',
              'new_footprints': len(new_refs), 'placements': placements,
              'old_tracks_and_vias': old_track_count,
              'removed_split_net_tracks_and_vias': removed,
              'remaining_tracks_and_vias': len(list(board.GetTracks())),
              'split_legacy_net_names': sorted({r['net'] for r in removed})}
    (project / 'placement-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Placed {len(new_refs)} new footprints; removed {len(removed)} split-net copper items.')
    print('No new routing was created. This is not a manufacturing-ready board.')
    del board
    del app


if __name__ == '__main__':
    main()
