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


# Original Redux outline (mm) and the band added above its top edge.
CORE_LEFT, CORE_TOP, CORE_RIGHT, CORE_BOTTOM = 29.2, 50.8, 260.98, 208.91
BAND_LEFT = 66.0      # J4 (DSUB, x 29..61) faces the top edge: keep the plug clear
BAND_RIGHT = CORE_RIGHT - 3.0
EDGE_GAP, H_GAP, V_GAP, BORDER = 3.0, 4.0, 6.0, 3.0
ROW_PENALTY = 60.0   # mm of x displacement traded for one row farther from the core
# Placement order: TIMING_REVIEW.md critical paths first (VA/CA bus, 16MHz capture,
# RAM /CE, WE path, CLK_MAR latches), then the palette/status logic, then sound.
PRIORITY = [('U68', 'U67'), ('U77', 'U66', 'U78', 'U79', 'U81', 'U83', 'U64', 'U71'),
            ('U69', 'U70', 'U80', 'U82', 'U88', 'U89', 'U90', 'U84', 'U85', 'U86', 'U87'),
            ('U72', 'U75', 'U65'), ('U74', 'X2')]
# Clock drivers: anchored at their core source instead of their net average.
PINNED = {'U68': 'X1', 'U67': 'U6'}
POWER = {'+5V', 'GND'}


def band_outline(top):
    """L-shaped outline: original rectangle plus the band, notched above J4."""
    return [(CORE_LEFT, CORE_TOP), (BAND_LEFT - 2.0, CORE_TOP), (BAND_LEFT - 2.0, top),
            (CORE_RIGHT, top), (CORE_RIGHT, CORE_BOTTOM), (CORE_LEFT, CORE_BOTTOM)]


def place_compact(pcbnew, board, footprints, manifest, pin_nets, new_refs,
                  row_penalty=None):
    """Anchor-ordered column packing in the top band; returns placements and info."""
    nets_of = {}
    members = {}
    for (ref, pin), net in pin_nets.items():
        if net in POWER:
            continue
        nets_of.setdefault(ref, set()).add(net)
        members.setdefault(net, set()).add(ref)
    core_x = {}
    for ref, fp in footprints.items():
        if ref in new_refs:
            continue
        for pad in fp.Pads():
            net = pin_nets.get((ref, pad.GetNumber()))
            if net and net not in POWER:
                core_x.setdefault(net, []).append(pcbnew.ToMM(pad.GetPosition().x))
    anchors = {}
    for ref in sorted(new_refs):  # weighted by 1/fanout so buses do not dominate
        pairs = [(sum(core_x[n])/len(core_x[n]), 1/len(members[n]))
                 for n in sorted(nets_of.get(ref, ())) if n in core_x]
        if pairs:
            anchors[ref] = sum(x*w for x, w in pairs)/sum(w for _, w in pairs)
    for _ in range(4):  # propagate to parts with no core neighbour (e.g. PSG audio)
        for ref in sorted(new_refs - set(anchors)):
            near = [anchors[o] for n in sorted(nets_of.get(ref, ())) for o in sorted(members[n])
                    if o in anchors and o != ref]
            if near:
                anchors[ref] = sum(near)/len(near)
    for ref in sorted(new_refs - set(anchors)):
        anchors[ref] = (BAND_LEFT+BAND_RIGHT)/2
    weight = {ref: sum(1 for n in nets_of.get(ref, ()) if n in core_x) for ref in new_refs}
    for ref, core in PINNED.items():  # clock drivers sit next to their core source
        if ref in new_refs and core in footprints:
            anchors[ref] = pcbnew.ToMM(footprints[core].GetPosition().x)

    def decoupler(ref):
        return f'C{34+int(ref[1:])-64}'
    hosts = [r for r in sorted(new_refs) if (r.startswith('U') and r != 'U76') or r == 'X2']
    caps = {decoupler(r) if r != 'X2' else 'C63' for r in hosts}
    cell_parts = {h: [] for h in hosts}
    for ref in sorted(new_refs - set(hosts) - caps):
        shared = {h: len(nets_of.get(ref, set()) & nets_of.get(h, set())) for h in hosts}
        best = max(sorted(shared), key=lambda h: shared[h])
        if shared[best] == 0:  # e.g. bulk capacitor: nearest anchor
            best = min(hosts, key=lambda h: abs(anchors[h]-anchors[ref]))
        cell_parts[best].append(ref)

    def size(fp):
        box = fp.GetBoundingBox()
        return pcbnew.ToMM(box.GetWidth()), pcbnew.ToMM(box.GetHeight())

    def put(fp, x, y, angle):  # top-left of bounding box at (x, y)
        fp.SetOrientationDegrees(angle)
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        box = fp.GetBoundingBox()
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x - pcbnew.ToMM(box.GetX())),
                                     pcbnew.FromMM(y - pcbnew.ToMM(box.GetY()))))

    cells = []
    for host in hosts:
        parts = [host, 'C63' if host == 'X2' else decoupler(host)] + cell_parts[host]
        widths, height = [], 0.0
        for ref in parts:
            fp = footprints[ref]
            fp.SetOrientationDegrees(90 if ref.startswith('U') and ref != 'U76' else
                                     90 if ref.startswith('R') else 0)
            w, h = size(fp)
            widths.append(w)
            height = max(height, h)
        cells.append({'host': host, 'parts': parts, 'anchor': anchors[host],
                      'weight': weight[host], 'width': sum(widths)+1.0*(len(parts)-1),
                      'height': height})
    # Row legalization by timing priority (TIMING_REVIEW.md): critical cells are
    # placed first and claim the rows nearest the core edge; each cell takes the
    # free interval closest to its anchor, trading ROW_PENALTY mm per row.
    tier = {ref: rank for rank, group in enumerate(PRIORITY) for ref in group}
    cells.sort(key=lambda c: (tier.get(c['host'], len(PRIORITY)), -c['weight'], c['anchor']))
    penalty = ROW_PENALTY if row_penalty is None else row_penalty
    rows = []  # each: {'busy': [(x0, x1)], 'cells': [...]}

    def best_x(busy, want, width):
        edges = sorted([(BAND_LEFT - H_GAP, BAND_LEFT - H_GAP)] + busy +
                       [(BAND_RIGHT + H_GAP, BAND_RIGHT + H_GAP)])
        best = None
        for (_, start), (end, _) in zip(edges, edges[1:]):
            lo, hi = start + H_GAP, end - H_GAP - width
            if hi < lo:
                continue
            x = min(max(want, lo), hi)
            if best is None or abs(x - want) < abs(best - want):
                best = x
        return best

    for cell in cells:
        want = cell['anchor'] - cell['width']/2
        choice = None
        for index in range(len(rows)+1):
            busy = rows[index]['busy'] if index < len(rows) else []
            x = best_x(busy, want, cell['width'])
            if x is None:
                continue
            cost = abs(x - want) + penalty*index
            if choice is None or cost < choice[0]:
                choice = (cost, index, x)
        if choice is None:
            raise ValueError(f'{cell["host"]} cell wider than the band')
        _, index, x = choice
        if index == len(rows):
            rows.append({'busy': [], 'cells': []})
        cell['x'] = x
        rows[index]['cells'].append(cell)
        rows[index]['busy'].append((x, x + cell['width']))
    placements = {}
    y = CORE_TOP - EDGE_GAP
    for row in rows:
        height = max(c['height'] for c in row['cells'])
        y -= height
        for cell in row['cells']:
            cx = cell['x']
            for ref in cell['parts']:
                fp = footprints[ref]
                w, h = size(fp)
                put(fp, cx, y + (height-h)/2, fp.GetOrientationDegrees())
                placements[ref] = [round(pcbnew.ToMM(fp.GetPosition().x), 3),
                                   round(pcbnew.ToMM(fp.GetPosition().y), 3),
                                   fp.GetOrientationDegrees()]
                cx += w + 1.0
        y -= V_GAP
    top = y + V_GAP - BORDER
    if set(placements) != new_refs:
        raise ValueError(f'Unplaced parts: {sorted(new_refs-set(placements))}')
    return placements, {'top': round(top, 2),
                        'anchors': {r: round(anchors[r], 1) for r in sorted(new_refs)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=HERE / 'integrated')
    parser.add_argument('--row-penalty', type=float, default=ROW_PENALTY,
                        help='mm of x displacement traded for one band row (layout study)')
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
    # Compact band placement (TIMING_REVIEW.md 8절 3번).  The board grows upward
    # from its original top edge; the VGA connector J4, which faces that edge,
    # keeps a notch.  Each new part is anchored at the weighted mean x of the
    # core pads it shares signal nets with, so extension logic sits directly
    # above the core circuitry it talks to.
    placements, cells = place_compact(pcbnew, board, footprints, manifest, pin_nets, new_refs,
                                      args.row_penalty)
    old_edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    for edge in old_edges:
        board.Remove(edge)
    outline = band_outline(cells['top'])
    for a, b in zip(outline, outline[1:] + outline[:1]):
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.05))
        board.Add(seg)
    note = pcbnew.PCB_TEXT(board)
    note.SetText('COLOR + SN76489 DRAFT / UNROUTED / DO NOT FABRICATE')
    note.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(BAND_LEFT + 60),
                                     pcbnew.FromMM(cells['top'] + 2.5)))
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
              'layout': 'compact top band', 'row_penalty_mm': args.row_penalty, 'outline_mm': band_outline(cells['top']),
              'anchors_mm': cells['anchors'],
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
