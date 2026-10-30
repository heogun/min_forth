#!/usr/bin/env python3
"""Generate an integrated schematic draft from the corrected, immutable baseline.

This deliberately does not claim to route the PCB or verify analog timing.
"""

import argparse
import csv
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET

from cad_sexpr import parse, quoted, replace
from check_kicad import HERE, PROJECT, find_cli
from extension_design import SOURCES, design, net_name
from prepare_cad import hierarchy, properties, export_netlist, fingerprint


KICAD = Path('/Applications/KiCad/KiCad.app/Contents')
SYMBOLS = KICAD / 'SharedSupport/symbols'
NAMESPACE = uuid.UUID('53761c37-1a9a-4cf2-a1c3-b80a4ab9c191')
SHEETS = ['ExtensionIO', 'PSG', 'Attribute', 'Palette', 'ExtensionPower']


def uid(name):
    return str(uuid.uuid5(NAMESPACE, name))


def q(value):
    return json.dumps(str(value), ensure_ascii=False)


def point(node):
    return tuple(round(float(node.value(i)), 6) for i in (1, 2))


def block(text, root, additions):
    return text[:root.end - 1] + '\n' + '\n'.join(additions) + '\n' + text[root.end - 1:]


def std_pins(library, name):
    root = parse((SYMBOLS / f'{library}.kicad_sym').read_text())
    definitions = {s.value(): s for s in root.nodes('symbol')}
    if name not in definitions:
        frozen = parse((HERE / 'cad/Redux.kicad_sym').read_text())
        matches = [s for s in frozen.nodes('symbol') if s.value().endswith('__'+name)]
        if not matches:
            raise ValueError(f'No verified pinout for {library}:{name}')
        symbol = matches[0]
    else:
        symbol = definitions[name]
    while symbol.nodes('extends'):
        symbol = definitions[symbol.one('extends').value()]
    result = {}
    for unit in symbol.nodes('symbol'):
        # Alternate De Morgan bodies have identical physical pins.
        for pin in unit.nodes('pin'):
            number = pin.one('number').value()
            result.setdefault(number, (pin.one('name').value(), pin.value()))
    return result


def pin_definitions():
    sources = {
        'HC30': ('74xx', '74LS30'), 'HC04': ('74xx', '74HC04'),
        'HC138': ('74xx', '74HC138'), 'HC11': ('74xx', '74LS11'),
        'HC173': ('74xx', '74HC173'), 'HC574': ('74xx', '74HC574'),
        'HC32': ('74xx', '74HC32'), 'SN76489AN': ('Audio', 'SN76489AN'),
        'HCT244': ('74xx', '74HCT244'), 'HC283': ('74xx', '74LS283'),
        'HC86': ('74xx', '74HC86'), 'HC245': ('74xx', '74HC245'),
        'HC377': ('74xx', '74LS377'), 'HC74': ('74xx', '74HC74'),
        'HCT377': ('74xx', '74LS377'),
        'HC08': ('74xx', '74HC08'), 'HC4002': ('74xx', '74HC4002'),
        'HC157': ('74xx', '74LS157'), 'AC244': ('74xx', '74LS244'),
        'POR': ('Power_Supervisor', 'MCP120-xxxDxTO'),
        '2N7000': ('Transistor_FET', '2N7000'),
    }
    result = {key: std_pins(*value) for key, value in sources.items()}
    result['R'] = {'1': ('1', 'passive'), '2': ('2', 'passive')}
    result['C'] = dict(result['R'])
    result['CP'] = dict(result['R'])
    result['CONN2'] = dict(result['R'])
    result['OSC'] = {'1': ('NC', 'no_connect'), '14': ('VCC', 'power_in'),
                     '7': ('GND', 'power_in'), '8': ('OUT', 'output')}
    old = parse((HERE / 'cad/Redux.kicad_sym').read_text())
    symbol = next(s for s in old.nodes('symbol') if s.value().endswith('__AS6C62256'))
    result['SRAM'] = {p.one('number').value(): (p.one('name').value(), p.value())
                      for p in symbol.walk() if p.name == 'pin'}
    return result


def package_symbol(name, pins):
    if name in ('R', 'C', 'CP', 'CONN2'):
        library, original_name = {
            'R': ('Device', 'R'), 'C': ('Device', 'C'),
            'CP': ('Device', 'C_Polarized'), 'CONN2': ('Connector_Generic', 'Conn_01x02'),
        }[name]
        text = (SYMBOLS / f'{library}.kicad_sym').read_text()
        root = parse(text)
        original = next(s for s in root.nodes('symbol') if s.value() == original_name)
        if original.nodes('extends'):
            raise ValueError(f'Passive symbol unexpectedly inherited: {original_name}')
        edits = [quoted(original.children[1], name)]
        positions = {}
        for body in original.nodes('symbol'):
            edits.append(quoted(body.children[1], name+body.value()[len(original_name):]))
            for pin in body.nodes('pin'):
                positions[pin.one('number').value()] = point(pin.one('at'))
        # Edits can alter the definition length; extract the renamed symbol afresh.
        full = replace(text, edits)
        copied = next(s for s in parse(full).nodes('symbol') if s.value() == name)
        definition = full[copied.start:copied.end]
        return definition, positions, max(abs(y) for _, y in positions.values())+2.54
    # Full-package symbols make every gate input and power pin auditable.
    left, right = [], []
    for number, (label, typ) in sorted(pins.items(), key=lambda p: int(p[0])):
        (right if typ in ('output', 'tri_state', 'open_collector', 'bidirectional')
         else left).append((number, label or f'P{number}', typ))
    half_height = max(5.08, (max(len(left), len(right)) + 1) * 1.27)
    positions = {}
    pin_text = []
    for side, entries in [(-1, left), (1, right)]:
        for index, (number, label, typ) in enumerate(entries):
            x = side * 17.78
            y = (len(entries) - 1) * 1.27 - index * 2.54
            positions[number] = (x, y)
            angle = 0 if side == -1 else 180
            pin_text.append(f'''(pin {typ} line (at {x:g} {y:g} {angle}) (length 2.54)
              (name {q(label)} (effects (font (size 0.8 0.8))))
              (number {q(number)} (effects (font (size 0.8 0.8)))))''')
    definition = f'''(symbol {q(name)} (pin_names (offset 0.5))
      (exclude_from_sim no) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 {half_height+2:g} 0) (effects (font (size 1 1))))
      (property "Value" {q(name)} (at 0 {-half_height-2:g} 0) (effects (font (size 1 1))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1 1)) (hide yes)))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1 1)) (hide yes)))
      (property "Description" "Full-package pinout; integrated design draft" (at 0 0 0)
          (effects (font (size 1 1)) (hide yes)))
      (symbol {q(name+'_0_1')} (rectangle (start -15.24 {half_height:g})
          (end 15.24 {-half_height:g}) (stroke (width 0.254) (type default))
          (fill (type background))))
      (symbol {q(name+'_1_1')} {' '.join(pin_text)}))'''
    return definition, positions, half_height


def label(name, x, y, angle=0, token=''):
    return f'''(global_label {q(name)} (shape bidirectional) (at {x:g} {y:g} {angle})
       (effects (font (size 0.8 0.8)) (justify {'right' if angle == 180 else 'left'}))
       (uuid {q(uid('label:'+token+':'+name+':'+str((x,y))))}))'''


def wire(a, b, token):
    return f'''(wire (pts (xy {a[0]:g} {a[1]:g}) (xy {b[0]:g} {b[1]:g}))
       (stroke (width 0) (type default)) (uuid {q(uid('wire:'+token))}))'''


def attach(name, position, token):
    # A global label may be attached directly to an existing connected pin.
    return label(name, *position, token=token)


def instance(part, x, y, positions, height, root_uuid, pins):
    attrs = []
    for name, value, py, hide in [
        ('Reference', part.ref, y-height-3, False), ('Value', part.value, y+height+3, False),
        ('Footprint', part.footprint, y, True), ('Datasheet', '', y, True),
        ('Description', 'Integrated extension draft - see CIRCUIT.md', y, True)]:
        attrs.append(f'''(property {q(name)} {q(value)} (at {x:g} {py:g} 0)
          (effects (font (size 0.9 0.9)) {'(hide yes)' if hide else ''}))''')
    component = f'''(symbol (lib_id {q('Extensions:'+part.symbol)}) (at {x:g} {y:g} 0)
       (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
       (uuid {q(uid('part:'+part.ref))}) {' '.join(attrs)}
       {' '.join(f'(pin {q(n)} (uuid {q(uid(part.ref+".pin:"+n))}))' for n in positions)}
       (instances (project {q(PROJECT)} (path {q('/'+root_uuid+'/'+uid('sheet:'+part.sheet))}
          (reference {q(part.ref)}) (unit 1)))))'''
    additions = [component]
    for number, (dx, dy) in positions.items():
        position = (x+dx, y-dy)
        net = part.pins.get(number)
        if net is None:
            additions.append(f'(no_connect (at {position[0]:g} {position[1]:g}) '
                             f'(uuid {q(uid(part.ref+".NC:"+number))}))')
        else:
            endpoint = (position[0] + (-2.54 if dx < 0 else 2.54), position[1])
            additions.append(wire(position, endpoint, part.ref+'.'+number))
            additions.append(label(net, *endpoint, angle=180 if dx < 0 else 0,
                                   token=part.ref+'.'+number))
    return additions


def pin_position(root, ref, number):
    definitions = {s.value(): s for s in root.one('lib_symbols').nodes('symbol')}
    for inst in root.nodes('symbol'):
        if properties(inst)['Reference'].value(2) != ref:
            continue
        symbol = definitions[inst.one('lib_id').value()]
        unit = int(inst.one('unit').value())
        for body in symbol.nodes('symbol'):
            if int(body.value().rsplit('_', 2)[1]) not in (0, unit):
                continue
            for pin in body.nodes('pin'):
                if pin.one('number').value() != number:
                    continue
                dx, dy = point(pin.one('at'))
                sx, sy = point(inst.one('at'))
                angle = math.radians(float(inst.one('at').value(3)))
                tx = math.cos(angle)*dx-math.sin(angle)*dy
                ty = -math.sin(angle)*dx-math.cos(angle)*dy
                if inst.nodes('mirror'):
                    mirror = inst.one('mirror').value()
                    if mirror == 'x':
                        ty = -ty
                    elif mirror == 'y':
                        tx = -tx
                    else:
                        raise ValueError(f'Unsupported mirror: {mirror}')
                return round(sx+tx, 6), round(sy+ty, 6)
    raise ValueError(f'Cannot locate {ref}.{number}')


def on_segment(p, a, b):
    cross = (p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])
    return abs(cross) < 1e-5 and min(a[0], b[0])-1e-6 <= p[0] <= max(a[0], b[0])+1e-6 and (
        min(a[1], b[1])-1e-6 <= p[1] <= max(a[1], b[1])+1e-6)


def detach_net(text, root, ref, pin):
    """Remove a complete, explicitly reconnected small network, not component pins."""
    positions = {pin_position(root, ref, pin)}
    wires = []
    for w in root.nodes('wire'):
        coords = [point(p) for p in w.one('pts').nodes('xy')]
        wires.append((w, *coords))
    selected = set()
    changed = True
    while changed:
        changed = False
        for i, (_, a, b) in enumerate(wires):
            if i not in selected and any(on_segment(p, a, b) for p in positions):
                selected.add(i)
                positions.update([a, b])
                changed = True
    edits = [(wires[i][0].start, wires[i][0].end, '') for i in selected]
    for kind in ('junction', 'label', 'global_label'):
        for node in root.nodes(kind):
            p = point(node.one('at'))
            if p in positions or any(on_segment(p, wires[i][1], wires[i][2]) for i in selected):
                edits.append((node.start, node.end, ''))
    return edits


def modify_core(destination):
    replacements = {
        'VGA.kicad_sch': [('J4', '1'), ('U35', '13'), ('U36', '27')],
        'RAM.kicad_sch': [('U34', '22')],
    }
    new_connections = {
        'VGA.kicad_sch': {
            ('J4', '1'): 'CS_VGA_R', ('J4', '2'): 'CS_VGA_G', ('J4', '3'): 'CS_VGA_B',
            ('R6', '1'): 'CS_DAC_R', ('R6', '2'): 'CS_VGA_R', ('U35', '13'): 'CS_PIXEL',
            ('U1', '13'): 'CS_VGA_WE_RAW', ('U36', '27'): 'CS_BITMAP_WE_N'},
        'RAM.kicad_sch': {('U34', '22'): 'CS_RAM_INH', ('J3', '3'): 'CS_INH_EXT',
                         ('R5', '2'): 'CS_INH_EXT'},
    }
    for filename, (text, root) in hierarchy(destination).items():
        edits, additions = [], []
        for ref, pin in replacements.get(filename, []):
            edits.extend(detach_net(text, root, ref, pin))
        # Deletion networks must be disjoint; duplicate deletion is an error.
        edits = list({(a, b): (a, b, c) for a, b, c in edits}.values())
        for (ref, pin), net in new_connections.get(filename, {}).items():
            additions.append(attach(net, pin_position(root, ref, pin), ref+'.'+pin))
        for logical, (sheet, ref, pin) in SOURCES.items():
            if sheet != filename:
                continue
            canonical = net_name(logical)
            if canonical.startswith('A') and canonical[1:].isdigit() or canonical in ('CLK_MAR', '~{RESET}'):
                continue  # These are already globals in the baseline.
            additions.append(attach(canonical, pin_position(root, ref, pin), ref+'.'+pin))
        renames = {}
        if filename == 'VGA.kicad_sch':
            renames = {**{f'B{i}': f'CS_VDATA{i}' for i in range(8)},
                       **{f'V_A{i}': f'CS_VA{i}' for i in range(14)},
                       'VREG_CP': 'CS_VREG_CP', 'V256': 'CS_V256', '~{VGA_WE}': 'CS_VGA_WE_RAW'}
        elif filename == 'RAM.kicad_sch':
            renames = {'INH': 'CS_INH_EXT'}
        deleted = {(a, b) for a, b, _ in edits}
        for local in root.nodes('label'):
            if local.value() in renames and (local.start, local.end) not in deleted:
                replacement = label(renames[local.value()], *point(local.one('at')),
                                    token='promote:'+local.one('uuid').value())
                edits.append((local.start, local.end, replacement))
        # Promoted labels already export these nets; avoid superposed duplicate labels.
        promoted = set(renames.values())
        additions = [a for a in additions if parse(a).value() not in promoted]
        for inst in root.nodes('symbol'):
            props = properties(inst)
            ref = props['Reference'].value(2)
            if ref in ('R2', 'R6'):
                edits.append(quoted(props['Value'].children[2], '4.7k' if ref == 'R2' else '750'))
        if edits or additions:
            text = replace(text, edits)
            text = block(text, parse(text), additions)
            (destination / filename).write_text(re.sub(r'(?m)^[ \t]+$', '', text))


def generate(source, destination):
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and destination must not contain each other')
    if destination.exists():
        raise ValueError(f'Refusing to overwrite {destination}')
    source_before = fingerprint(source)
    destination.mkdir(parents=True)
    for p in source.iterdir():
        if p.suffix in ('.kicad_sch', '.kicad_pcb', '.kicad_pro', '.kicad_sym') or p.name in (
                'fp-lib-table', 'sym-lib-table'):
            shutil.copy2(p, destination / p.name)
        elif p.is_dir() and p.name.endswith('.pretty'):
            shutil.copytree(p, destination / p.name)
    core = parse((source / f'{PROJECT}.kicad_sch').read_text())
    root_uuid = core.one('uuid').value()
    parts, gates = design()
    pins = pin_definitions()
    for part in parts:
        for number, (name, typ) in pins[part.symbol].items():
            if number not in part.pins:
                if typ == 'power_in':
                    part.pins[number] = 'GND' if name in ('GND', 'VSS') else '+5V'
                elif typ == 'input':
                    part.pins[number] = 'GND'
        if set(part.pins) - set(pins[part.symbol]):
            raise ValueError(f'Invalid physical pins on {part.ref}: {set(part.pins)-set(pins[part.symbol])}')
    definitions = {name: package_symbol(name, physical) for name, physical in pins.items()}
    (destination / 'Extensions.kicad_sym').write_text(
        '(kicad_symbol_lib (version 20241209) (generator "redux_extensions")\n'
        + '\n'.join(d[0] for d in definitions.values()) + '\n)\n')
    table = (destination / 'sym-lib-table').read_text()
    end = table.rfind(')')
    (destination / 'sym-lib-table').write_text(table[:end] +
        '(lib (name "Extensions")(type "KiCad")(uri "${KIPRJMOD}/Extensions.kicad_sym")'
        '(options "")(descr "Pin-level integrated extension draft"))\n'+table[end:])
    for index, sheet in enumerate(SHEETS):
        sheet_parts = [p for p in parts if p.sheet == sheet]
        names = sorted({p.symbol for p in sheet_parts})
        lib_symbols = []
        for name in names:
            definition = definitions[name][0]
            node = parse(definition)
            lib_symbols.append(replace(definition, [quoted(node.children[1], 'Extensions:'+name)]))
        additions = []
        large = [p for p in sheet_parts if p.ref.startswith('U') or p.ref.startswith('X')]
        small = [p for p in sheet_parts if p not in large]
        for i, part in enumerate(large):
            x, y = 65 + (i % 3)*130, 65 + (i // 3)*80
            x, y = round(x/1.27)*1.27, round(y/1.27)*1.27
            additions += instance(part, x, y, definitions[part.symbol][1],
                                  definitions[part.symbol][2], root_uuid, pins)
        for i, part in enumerate(small):
            x, y = 45 + (i % 5)*78, (35 + (i // 5)*38 if sheet == 'ExtensionPower'
                                       else 35 + math.ceil(len(large)/3)*80 + (i // 5)*28)
            x, y = round(x/1.27)*1.27, round(y/1.27)*1.27
            # Sound has many passives: put them on a separate sub-sheet.
            if y > (390 if sheet == 'Palette' else 270):
                raise ValueError(f'Sheet {sheet} overflow: {part.ref} at y={y}')
            additions += instance(part, x, y, definitions[part.symbol][1],
                                  definitions[part.symbol][2], root_uuid, pins)
        text = f'''(kicad_sch (version 20250114) (generator "eeschema")
          (uuid {q(uid('document:'+sheet))}) (paper {q('A2' if sheet == 'Palette' else 'A3')})
          (title_block (title {q(sheet+' - Color/SN76489 integration DRAFT')})
             (date "2026-10-30") (rev "CS-DRAFT-1")
             (comment 1 "NOT FOR FABRICATION: PCB routing/timing validation pending")
             (comment 3 "Derived from slu4 Redux; CC BY-NC-SA 4.0"))
          (lib_symbols {' '.join(lib_symbols)}) {' '.join(additions)})\n'''
        (destination / f'{sheet}.kicad_sch').write_text(text)
    # Modify the baseline only after all new sheet instances are well formed.
    modify_core(destination)
    root_path = destination / f'{PROJECT}.kicad_sch'
    text = root_path.read_text()
    root = parse(text)
    paper = root.one('paper')
    title = root.one('title_block')
    text = replace(text, [(paper.start, paper.end, '(paper "A3")'),
        quoted(title.one('title').children[1], 'Minimal 64x4 Redux - Color/SN76489 integration DRAFT'),
        quoted(title.one('date').children[1], '2026-10-30'),
        quoted(title.one('rev').children[1], 'CS-DRAFT-1')])
    additions = []
    for i, sheet in enumerate(SHEETS):
        x, y = 225, 30+i*48
        additions.append(f'''(sheet (at {x} {y}) (size 155 30)
          (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
          (stroke (width 0) (type solid)) (fill (color 0 0 0 0))
          (uuid {q(uid('sheet:'+sheet))})
          (property "Sheetname" {q(sheet)} (at {x} {y} 0)
            (effects (font (size 1.27 1.27)) (justify left bottom)))
          (property "Sheetfile" {q(sheet+'.kicad_sch')} (at {x} {y+30} 0)
            (effects (font (size 1.27 1.27)) (justify left top)))
          (instances (project {q(PROJECT)} (path {q('/'+root_uuid)} (page {q(str(11+i))})))) )''')
    root_path.write_text(block(text, parse(text), additions))
    fp_table = (destination / 'fp-lib-table').read_text()
    names = set(re.findall(r'\(name "([^"]+)"\)', fp_table))
    extra = []
    for lib in sorted({p.footprint.split(':')[0] for p in parts}-names):
        extra.append(f'(lib (name {q(lib)})(type "KiCad")'
                     f'(uri "${{KICAD10_FOOTPRINT_DIR}}/{lib}.pretty")(options "")(descr ""))')
    end = fp_table.rfind(')')
    (destination / 'fp-lib-table').write_text(fp_table[:end]+'\n'.join(extra)+'\n'+fp_table[end:])
    manifest = {'status': 'SCHEMATIC DRAFT - PCB UNROUTED',
                'parts': [asdict(p) for p in parts], 'gates': gates,
                'symbol_pins': {name: {num: {'name': label, 'type': typ} for num, (label, typ)
                                          in physical.items()} for name, physical in pins.items()},
                'source_sha256': source_before}
    (destination / 'extension-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    with (destination / 'extension-bom.csv').open('w', newline='') as output:
        writer = csv.writer(output, lineterminator='\n')
        writer.writerow(['Reference', 'Value', 'Footprint', 'Schematic sheet'])
        writer.writerows((p.ref, p.value, p.footprint, p.sheet) for p in parts)
    export_netlist(find_cli(), destination, destination / 'integrated.net.xml')
    netlist = destination / 'integrated.net.xml'
    netlist.write_text(netlist.read_text().replace(str(destination), '${KIPRJMOD}'))
    (destination / '.gitignore').write_text('*-backups/\n*.kicad_prl\n*.lck\nfp-info-cache\n')
    (destination / 'PROVENANCE.md').write_text('''# Integrated color/SN76489 draft

Original: Carsten Herting (slu4), Minimal 64x4 Home Computer, Revision 1.4 Redux.
Upstream: https://github.com/slu4coder/Minimal-64x4-Home-Computer
Reference commit: 1a59c95695d1a6a6147584465ee87803fe9387da.

Derived from this workspace's corrected `../cad/` baseline. Original attribution and
CC BY-NC-SA 4.0 notices are retained. Library definitions retain their applicable terms.
License: https://creativecommons.org/licenses/by-nc-sa/4.0/
Legal code: https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode

Modified 2026-10-30: Attribute color, SN76489AN, decoding/control, RGB DAC, reset/mute,
power parts, and PCB footprint/net synchronization. See `../CIRCUIT.md` for status.
No external expansion-card CAD was copied wholesale.

**NOT FOR FABRICATION.** This is an electrical/placement draft, not a validated 8MHz
design or upstream endorsement. Routing, maximum timing and real hardware tests are
pending. No manufacturing Gerbers are provided. Supplied as-is, without warranty.
''')
    if fingerprint(source) != source_before:
        raise ValueError('Baseline changed during generation')
    print(f'Generated integrated schematic: {len(parts)} new parts, {len(SHEETS)} sheets.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE / 'cad')
    parser.add_argument('--destination', type=Path, default=HERE / 'integrated')
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        parser.error('Source and destination must not contain each other')
    if destination.exists():
        parser.error(f'Refusing to overwrite {destination}')
    build = HERE / 'build'
    build.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='extension-stage-', dir=build)) / 'project'
    generate(source, stage)
    stage.rename(destination)


if __name__ == '__main__':
    main()
