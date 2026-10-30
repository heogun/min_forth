#!/usr/bin/env python3
"""Create a corrected, self-contained Redux baseline; never overwrite a CAD tree."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from cad_sexpr import parse, quoted, replace
from check_kicad import HERE, ROOT, PROJECT, find_cli, fingerprint


CUSTOM = {'J1', 'J3', 'J5', 'RN1'}


def properties(node):
    return {p.value(): p for p in node.nodes('property')}


def hierarchy(source):
    found = {}

    def visit(path):
        if path.name in found:
            return
        text = path.read_text()
        root = parse(text)
        found[path.name] = (text, root)
        for sheet in root.nodes('sheet'):
            visit(path.parent / properties(sheet)['Sheetfile'].value(2))

    visit(source / f'{PROJECT}.kicad_sch')
    return found


def symbol_name(old_id):
    return re.sub(r'[^A-Za-z0-9_]', '_', old_id.replace(':', '__'))


def freeze_symbols(sheets, destination):
    definitions = {}
    library = []
    for text, root in sheets.values():
        for symbol in root.one('lib_symbols').nodes('symbol'):
            old = symbol.value()
            raw = text[symbol.start:symbol.end]
            if old in definitions:
                if re.sub(r'\s+', '', raw) != re.sub(r'\s+', '', definitions[old]):
                    raise ValueError(f'Conflicting embedded definitions: {old}')
                continue
            definitions[old] = raw
            short = old.split(':', 1)[1]
            name = symbol_name(old)
            local = parse(raw)
            edits = [quoted(local.children[1], name)]
            for unit in local.nodes('symbol'):
                if not unit.value().startswith(short + '_'):
                    raise ValueError(f'Unexpected symbol unit name: {unit.value()}')
                edits.append(quoted(unit.children[1], name + unit.value()[len(short):]))
            library.append(replace(raw, edits))
    (destination / 'Redux.kicad_sym').write_text(
        '(kicad_symbol_lib (version 20241209) (generator "redux_baseline")\n'
        + '\n'.join(library) + '\n)\n')
    return len(definitions)


def write_schematics(sheets, destination):
    for filename, (text, root) in sheets.items():
        edits = []
        for symbol in root.one('lib_symbols').nodes('symbol'):
            old = symbol.value()
            name = symbol_name(old)
            short = old.split(':', 1)[1]
            edits.append(quoted(symbol.children[1], 'Redux:' + name))
            for unit in symbol.nodes('symbol'):
                edits.append(quoted(unit.children[1], name + unit.value()[len(short):]))
        for symbol in root.nodes('symbol'):
            lib_id = symbol.one('lib_id').children[1]
            edits.append(quoted(lib_id, 'Redux:' + symbol_name(lib_id.value)))
            props = properties(symbol)
            if props['Reference'].value(2) in CUSTOM:
                prop = props['Footprint'].children[2]
                edits.append(quoted(prop, 'Redux_Footprints:' + prop.value.split(':')[1]))
        (destination / filename).write_text(replace(text, edits))
    (destination / 'sym-lib-table').write_text(
        '(sym_lib_table\n'
        '  (lib (name "Redux")(type "KiCad")(uri "${KIPRJMOD}/Redux.kicad_sym")'
        '(options "")(descr "Frozen embedded Redux symbols; see PROVENANCE.md"))\n)\n')


def extract_footprints(source_board, destination):
    """Run with KiCad's Python so rotation is handled by the PCB API."""
    import wx
    app = wx.App(False)
    import pcbnew
    board = pcbnew.LoadBoard(str(source_board))
    library = destination / 'Redux_Footprints.pretty'
    library.mkdir(exist_ok=True)
    for footprint in board.GetFootprints():
        if footprint.GetReference() not in CUSTOM | {'G***'}:
            continue
        clone = pcbnew.Cast_to_FOOTPRINT(footprint.Duplicate(False))
        clone.SetOrientationDegrees(0)
        clone.SetPosition(pcbnew.VECTOR2I(0, 0))
        clone.SetReference('REF**')
        clone.SetValue(str(footprint.GetFPID().GetLibItemName()))
        target_library = library
        if footprint.GetReference() == 'G***':
            clone.SetAttributes(pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM
                                | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
            target_library = destination / 'logo.pretty'
        for pad in clone.Pads():
            pad.SetNetCode(0)
        pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(str(target_library), clone)
    del board
    del app


def repair_board(source, destination, components):
    text = (source / f'{PROJECT}.kicad_pcb').read_text()
    root = parse(text)
    edits = []
    for node in root.walk():
        if node.name == 'net' and len(node.children) > 2:
            name = node.children[2]
            if name.value == '/Control Logic/~{VGA_TRY}':
                edits.append(quoted(name, '/Control Logic/~{VGA_WIN}'))
    for fp in root.nodes('footprint'):
        props = properties(fp)
        ref = props['Reference'].value(2)
        if ref == 'G***':
            attr = fp.one('attr')
            edits.append((attr.start, attr.end,
                          '(attr board_only exclude_from_pos_files exclude_from_bom)'))
        else:
            component = components[ref]
            for name in ('Description', 'Datasheet'):
                field = component.find(f'./fields/field[@name="{name}"]')
                value = (field.text or '') if field is not None else ''
                if name in props:
                    atom = props[name].children[2]
                    if atom.value != value:
                        edits.append(quoted(atom, value))
            if ref in CUSTOM:
                edits.append(quoted(fp.children[1], 'Redux_Footprints:' + fp.value().split(':')[1]))
    for text_node in root.nodes('gr_text'):
        font = text_node.one('effects').one('font')
        # Use KiCad's built-in stroke font: no substituted platform TTF geometry.
        for face in font.nodes('face'):
            edits.append((face.start, face.end, ''))
        for cache in text_node.nodes('render_cache'):
            edits.append((cache.start, cache.end, ''))
        if text_node.value().startswith('HARDWARE  FEATURES'):
            size = font.one('size')
            edits.append((size.start, size.end, '(size 0.8 0.8)'))
            edits.append(quoted(text_node.children[1],
                'HARDWARE\nFEATURES\n-------------\nVon-Neumann\n8-bit ALU\n16-bit addr\n'
                '64K RAM\n512K FLASH\n8MHz CPU\n~1.85 MIPS\n(4x C64)\n'
                'VGA 400x240\nPS/2 + UART\nExpansion I/O\nNo CPU IC'))
            at = text_node.one('at')
            edits.append((at.start, at.end, '(at 93.34 99.06 0)'))
        if text_node.value() == 'READY.':
            at = text_node.one('at')
            edits.append((at.start, at.end, '(at 93.086 119.38 0)'))
    board = re.sub(r'(?m)^[ \t]+$', '', replace(text, edits))
    (destination / f'{PROJECT}.kicad_pcb').write_text(board)
    # Every copper segment, via, filled zone and pad geometry is unchanged.
    before = copper_signature(text)
    after = copper_signature(board)
    if before != after:
        raise ValueError('Board geometry changed unexpectedly')
    return before


def copper_signature(text):
    root = parse(text)
    records = []
    for name in ('segment', 'via', 'arc', 'zone'):
        for node in root.nodes(name):
            raw = text[node.start:node.end].replace('~{VGA_TRY}', '~{VGA_WIN}')
            records.append(raw)
    for footprint in root.nodes('footprint'):
        ref = properties(footprint)['Reference'].value(2)
        for name in ('at', 'pad'):
            for node in footprint.nodes(name):
                raw = text[node.start:node.end].replace('~{VGA_TRY}', '~{VGA_WIN}')
                records.append(ref + ':' + raw)
    return hashlib.sha256('\n'.join(records).encode()).hexdigest()


def net_signature(path):
    root = ET.parse(path).getroot()
    return sorted(tuple(sorted((n.get('ref'), n.get('pin')) for n in net.findall('node')))
                  for net in root.findall('./nets/net'))


def export_netlist(cli, project, output):
    result = subprocess.run([str(cli), 'sch', 'export', 'netlist', '--format', 'kicadxml',
                             '--output', str(output), str(project / f'{PROJECT}.kicad_sch')],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'minimal64/Revision 1.4 Redux/KiCAD9')
    parser.add_argument('--destination', type=Path, default=HERE / 'cad')
    parser.add_argument('--kicad-python', type=Path, default=Path(
        '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3'))
    parser.add_argument('--extract-footprints', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if args.extract_footprints:
        extract_footprints(source / f'{PROJECT}.kicad_pcb', destination)
        return
    if destination.exists():
        parser.error(f'Destination already exists; refusing to overwrite: {destination}')
    if source == destination or source in destination.parents or destination in source.parents:
        parser.error('Source and destination must not contain each other')
    before_hashes = fingerprint(source)
    cli = find_cli()
    sheets = hierarchy(source)
    destination.mkdir(parents=True)
    count = freeze_symbols(sheets, destination)
    write_schematics(sheets, destination)
    for name in ('ArduinoPC.pretty', 'logo.pretty'):
        shutil.copytree(source / name, destination / name)
        for footprint in (destination / name).glob('*.kicad_mod'):
            footprint.write_text(footprint.read_text())  # Normalize inherited CRLF to LF.
    tables = (source / 'fp-lib-table').read_text()
    libs = {'Redux_Footprints'}
    board_root = parse((source / f'{PROJECT}.kicad_pcb').read_text())
    for fp in board_root.nodes('footprint'):
        libs.add(fp.value().split(':')[0])
    entries = []
    for name in sorted(libs - {'ArduinoPC', 'logo'}):
        uri = '${KIPRJMOD}/Redux_Footprints.pretty' if name == 'Redux_Footprints' else (
            '${KICAD10_FOOTPRINT_DIR}/' + name + '.pretty')
        entries.append(f'(lib (name "{name}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n')
    end = tables.rfind(')')
    (destination / 'fp-lib-table').write_text(tables[:end] + ''.join(entries) + tables[end:])
    project = json.loads((source / f'{PROJECT}.kicad_pro').read_text())
    project['board']['design_settings']['drc_exclusions'] = []
    (destination / f'{PROJECT}.kicad_pro').write_text(json.dumps(project, indent=2) + '\n')
    reports = HERE / 'build/preparation'
    reports.mkdir(parents=True, exist_ok=True)
    export_netlist(cli, source, reports / 'before.xml')
    components = {c.get('ref'): c for c in ET.parse(reports / 'before.xml').findall('./components/comp')}
    signature = repair_board(source, destination, components)
    result = subprocess.run([str(args.kicad_python), str(Path(__file__).resolve()),
                             '--source', str(source), '--destination', str(destination),
                             '--extract-footprints'], capture_output=True, text=True)
    (reports / 'footprint-export.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Footprint export failed; see {reports / "footprint-export.log"}')
    export_netlist(cli, destination, reports / 'after.xml')
    if net_signature(reports / 'before.xml') != net_signature(reports / 'after.xml'):
        raise ValueError('Schematic pin-to-net connectivity changed')
    if fingerprint(source) != before_hashes:
        raise ValueError('Original source changed while preparing CAD')
    invariants = {
        'embedded_symbol_count': count, 'sheet_count': len(sheets),
        'schematic_connectivity_unchanged': True, 'copper_and_pad_geometry_sha256': signature,
        'copper_and_pad_geometry_unchanged': True,
        'source_unchanged': True,
        'source_sha256': {name: before_hashes[name] for name in sorted(before_hashes)
                          if name in sheets or name in (f'{PROJECT}.kicad_pcb', f'{PROJECT}.kicad_pro')},
    }
    (reports / 'invariants.json').write_text(json.dumps(invariants, indent=2) + '\n')
    (destination / 'baseline-invariants.json').write_text(json.dumps(invariants, indent=2) + '\n')
    print(f'Prepared {destination}: {len(sheets)} sheets, {count} frozen symbols')
    print('Verified unchanged schematic connectivity and PCB copper/pad geometry.')


if __name__ == '__main__':
    main()
