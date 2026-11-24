"""Digital/netlist checks only: not an analog timing or hardware-success oracle."""

import json
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

from check_kicad import HERE, ROOT, find_cli
from extension_design import SOURCES, net_name
from prepare_cad import export_netlist


PROJECT = HERE / 'integrated'


def nets(path):
    root = ET.parse(path).getroot()
    return {(n.get('ref'), n.get('pin')): net.get('name')
            for net in root.findall('./nets/net') for n in net.findall('node')}


def pld_value(spec, result):
    value = any(all(bool(result[net]) == level for net, level in product)
                for product in spec['products'])
    return not value if spec['active_low'] else value


def evaluate(manifest, values):
    """Evaluate the declared gate graph, the U64 PLD equations and U78 adder pins."""
    result = dict(values, **{'+5V': True, 'GND': False})
    parts = {p['ref']: p['pins'] for p in manifest['parts']}
    pending = list(manifest['gates'])
    pld_pending = {(ref, net): spec for ref, outputs in manifest.get('pld', {}).items()
                   for net, spec in outputs.items()}
    changed = True
    while changed:
        changed = False
        for key, spec in list(pld_pending.items()):
            if all(net in result for product in spec['products'] for net, _ in product):
                result[key[1]] = pld_value(spec, result)
                del pld_pending[key]
                changed = True
        for gate in list(pending):
            if not all(n in result for n in gate['inputs']):
                continue
            bits = [bool(result[n]) for n in gate['inputs']]
            op = gate['op']
            value = {'AND': lambda: all(bits), 'OR': lambda: any(bits),
                     'NOT': lambda: not bits[0], 'NAND': lambda: not all(bits),
                     'NOR': lambda: not any(bits), 'XOR': lambda: bits[0] != bits[1]}[op]()
            result[gate['output']] = value
            pending.remove(gate)
            changed = True
        adder = parts['U78']
        needed = [5, 3, 14, 12, 6, 2, 15, 11, 7]
        if all(adder[str(p)] in result for p in needed) and adder['9'] not in result:
            a = sum(int(bool(result[adder[str(p)]])) << i for i, p in enumerate([5, 3, 14, 12]))
            b = sum(int(bool(result[adder[str(p)]])) << i for i, p in enumerate([6, 2, 15, 11]))
            total = a+b+int(bool(result[adder['7']]))
            for i, p in enumerate([4, 1, 13, 10, 9]):
                result[adder[str(p)]] = bool(total & (1 << i))
            changed = True
    return result


@unittest.skipUnless((PROJECT / 'extension-manifest.json').exists(), 'Integrated draft not generated')
class ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((PROJECT / 'extension-manifest.json').read_text())
        cls.parts = {p['ref']: p for p in cls.manifest['parts']}
        cls.netmap = nets(PROJECT / 'integrated.net.xml')

    def test_all_manifest_pins_are_present_in_exported_schematic(self):
        for part in self.manifest['parts']:
            for pin, name in part['pins'].items():
                self.assertEqual(self.netmap[(part['ref'], pin)], name, (part['ref'], pin))

    def test_all_core_signal_taps_reach_the_intended_physical_pin(self):
        for logical, (_, ref, pin) in SOURCES.items():
            self.assertEqual(self.netmap[(ref, pin)], net_name(logical), (logical, ref, pin))

    def test_only_intended_core_connections_are_split(self):
        output = HERE / 'build/extension-tests'
        output.mkdir(parents=True, exist_ok=True)
        export_netlist(find_cli(), HERE / 'cad', output / 'baseline.xml')
        old = nets(output / 'baseline.xml')
        old_refs = {r for r, _ in old}
        changed = {('R6', '1'), ('R6', '2'), ('J4', '1'), ('J4', '2'), ('J4', '3'),
                   ('U36', '27'), ('U34', '22')}

        def groups(mapping):
            grouped = {}
            for pin, net in mapping.items():
                if pin[0] in old_refs and pin not in changed:
                    grouped.setdefault(net, set()).add(pin)
            return {frozenset(pins) for pins in grouped.values()}

        self.assertEqual(groups(old), groups(self.netmap))

    @unittest.skipUnless((ROOT / 'minforth/tools/asm').exists() and
        (ROOT / 'minimal64/Revision 1.4 Redux/Programs/asm/os.asm').exists(),
        'Native assembler/reference MinOS source not installed')
    def test_current_minos_kernel_ends_below_io_window(self):
        result = subprocess.run([str(ROOT / 'minforth/tools/asm'),
            str(ROOT / 'minimal64/Revision 1.4 Redux/Programs/asm/os.asm'), '-s'],
            check=True, capture_output=True, text=True)
        match = re.search(r'^#org 0x([0-9a-f]+) OS_Image_End:', result.stdout, re.M)
        self.assertIsNotNone(match)
        self.assertLessEqual(int(match.group(1), 16), 0xFEE0)

    def test_decode_and_ram_inhibit_cover_all_cpu_addresses(self):
        # Exercises the manifest PLD equations wired to U64's physical pins.
        for address in range(65536):
            inputs = {f'A{i}': bool(address & (1 << i)) for i in range(16)}
            inputs.update(CS_ATTR_MODE=False, CS_INH_EXT=False, **{'~{RI}': False, '~{RO}': False})
            result = evaluate(self.manifest, inputs)
            selected = address & 0xFFF0 == 0xFEE0
            self.assertEqual(bool(result['CS_RAM_INH']), selected, hex(address))
            self.assertEqual(not result['CS_SND_EN_N'], selected and address & 7 == 0)
            self.assertEqual(not result['CS_STATUS_OE_N'], selected and address & 7 == 1)
            self.assertEqual(not result['CS_CTRL_SEL_N'], selected and address & 7 == 2)
        inputs = {f'A{i}': bool(0xFEE0 & (1 << i)) for i in range(16)}
        inputs.update(CS_ATTR_MODE=False, CS_INH_EXT=False, **{'~{RI}': True, '~{RO}': True})
        result = evaluate(self.manifest, inputs)
        self.assertTrue(result['CS_SND_EN_N'])  # data latch loads only while ~RI is low
        self.assertTrue(result['CS_STATUS_OE_N'])  # status drives BUS only while ~RO is low
        for address in [0x0000, 0x3FFF, 0x4000, 0x430C, 0x7FFF, 0x8000, 0xFEE0, 0xFFFF]:
            for mode in (False, True):
                for external in (False, True):
                    inputs = {f'A{i}': bool(address & (1 << i)) for i in range(16)}
                    inputs.update(CS_ATTR_MODE=mode, CS_INH_EXT=external)
                    result = evaluate(self.manifest, inputs)
                    self.assertEqual(bool(result['CS_RAM_INH']), external or (
                        address & 0xFFF0 == 0xFEE0) or (mode and 0x4000 <= address < 0x8000))

    def test_ram_inhibit_is_a_single_pld_level_from_every_address_bit(self):
        # TIMING_REVIEW.md: RAM /CE must not pass through a multi-gate HC chain again.
        self.assertEqual(self.netmap[('U34', '22')], 'CS_RAM_INH')
        drivers = [(ref, pin) for (ref, pin), net in self.netmap.items()
                   if net == 'CS_RAM_INH' and ref != 'U34']
        self.assertEqual(drivers, [('U64', '23')])
        self.assertEqual(self.parts['U64']['symbol'], 'PAL22V10')
        for gate in self.manifest['gates']:
            self.assertNotEqual(gate['output'], 'CS_RAM_INH')
        pld_inputs = {net for product in self.manifest['pld']['U64']['CS_RAM_INH']['products']
                      for net, _ in product}
        self.assertEqual(pld_inputs, {f'A{i}' for i in range(4, 16)} |
                         {'CS_INH_EXT', 'CS_ATTR_MODE'})
        pins = self.parts['U64']['pins']
        for product in (p for spec in self.manifest['pld']['U64'].values()
                        for p in spec['products']):
            for net, _ in product:
                self.assertIn(net, pins.values(), net)  # every literal is a real U64 pin

    def test_galasm_source_matches_manifest_equations(self):
        text = (PROJECT / 'extension-decode.pld').read_text()
        lines = text.split('DESCRIPTION')[0].splitlines()
        self.assertEqual(lines[0], 'GAL22V10')
        pins = (lines[3] + ' ' + lines[4]).split()
        self.assertEqual(len(pins), 24)
        self.assertEqual((pins[11], pins[23]), ('GND', 'VCC'))
        by_name = {name: str(i+1) for i, name in enumerate(pins)}
        u64 = self.parts['U64']['pins']
        body = ' '.join(lines[5:]).replace(' + ', ' | ')
        equations = {}
        for statement in re.findall(r'(/?\w+)\s*=\s*([^=]+?)(?=\s+/?\w+(?:\.E)?\s*=|$)', body):
            target, expression = statement
            if target.endswith('.E'):
                continue
            equations[target] = [[(u64[by_name[lit.lstrip('/')]], not lit.startswith('/'))
                                  for lit in product.replace('*', ' ').split()]
                                 for product in expression.split('|')]
        for net, spec in self.manifest['pld']['U64'].items():
            name = next(n for n, pin in by_name.items() if u64.get(pin) == net)
            target = ('/' if spec['active_low'] else '') + name
            self.assertIn(target, equations, net)
            expected = [[(n, level) for n, level in product] for product in spec['products']]
            self.assertEqual(equations[target], expected, net)

    def test_attribute_row_phase_and_active_window_for_entire_raster(self):
        for y in range(260):
            for column in range(64):
                address = ((y & 255) << 6) | column
                inputs = {f'CS_VA{i}': bool(address & (1 << i)) for i in range(14)}
                inputs['CS_V256'] = y >= 256
                result = evaluate(self.manifest, inputs)
                row = sum(int(result[f'CS_CA{i}']) << (i-6) for i in range(6, 11))
                self.assertEqual(row, ((y+4) & 255) >> 3, (y, column))
                self.assertEqual(bool(result['CS_ACTIVE']), 12 <= column < 62 and 12 <= y < 252,
                                 (y, column))

    def test_exactly_one_ram_write_plane_can_be_active(self):
        for raw in (False, True):
            for attr in (False, True):
                result = evaluate(self.manifest, {'CS_VGA_WE_RAW': raw,
                    'CS_PENDING_ATTR': attr, 'CS_PENDING_BITMAP': not attr})
                writes = [not result['CS_BITMAP_WE_N'], not result['CS_ATTR_WE_N']]
                self.assertEqual(sum(writes), int(not raw))
                self.assertEqual(writes[1], not raw and attr)

    def test_psg_bit_order_ce_we_and_ready_interface(self):
        snd = self.parts['U74']['pins']
        latch = self.parts['U70']['pins']
        pin_info = self.manifest['symbol_pins']['SN76489AN']
        d_pins = {info['name']: num for num, info in pin_info.items() if info['name'].startswith('D')}
        for value in range(256):
            transmitted = 0
            for ti_bit in range(8):
                logical = int(snd[d_pins[f'D{ti_bit}']].removeprefix('CS_SND'))
                transmitted |= ((value >> logical) & 1) << (7-ti_bit)
            self.assertEqual(transmitted, value)
        self.assertEqual(self.parts['U70']['symbol'], 'HC377')
        self.assertEqual(latch['11'], 'CLK_MAR')  # Plain clock, not an address-gated clock.
        for i, pin in enumerate([3, 4, 7, 8, 13, 14, 17, 18]):
            self.assertEqual(latch[str(pin)], f'BUS{i}')
        self.assertEqual(snd['5'], snd['6'])
        self.assertEqual(self.parts['U75']['symbol'], 'HCT244')
        self.assertEqual(self.parts['U75']['pins']['2'], snd['4'])
        self.assertEqual(self.parts['U81']['symbol'], 'HCT377')  # SRAM TTL VOH to TTL input.

    def test_dac_has_16_distinct_colors_and_safe_nominal_full_scale(self):
        colors = set()
        for code in range(16):
            level = tuple(5*(int(bool(code & (1 << bit)))/750 + int(bool(code & 8))/1500)
                          / (1/75+1/750+1/1500) for bit in [2, 1, 0])
            colors.add(level)
            self.assertTrue(all(0 <= v <= 0.7 for v in level))
        self.assertEqual(len(colors), 16)
        worst = 5.25*(1/(750*0.99)+1/(1500*0.99))/(1/75+1/(750*0.99)+1/(1500*0.99))
        self.assertLessEqual(worst, 0.7)

    def test_pcb_draft_removes_only_intentionally_split_copper(self):
        report = json.loads((PROJECT / 'placement-report.json').read_text())
        self.assertEqual(report['new_footprints'], len(self.manifest['parts']))
        self.assertEqual(set(report['split_legacy_net_names']), {
            '/Memory and MAR/INH', '/VGA/~{VGA_WE}', 'Net-(J4-Pad1)', 'Net-(U35-Q7)'})
        self.assertEqual(report['old_tracks_and_vias']-report['remaining_tracks_and_vias'], 26)


if __name__ == '__main__':
    unittest.main()
