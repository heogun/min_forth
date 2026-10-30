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


def evaluate(manifest, values):
    """Evaluate the actual declared gate graph and U66/U78 combinational pins."""
    result = dict(values, **{'+5V': True, 'GND': False})
    parts = {p['ref']: p['pins'] for p in manifest['parts']}
    pending = list(manifest['gates'])
    changed = True
    while changed:
        changed = False
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
        decoder = parts['U66']
        if all(decoder[p] in result for p in ['1', '2', '3', '4', '5', '6']):
            enabled = not result[decoder['4']] and not result[decoder['5']] and result[decoder['6']]
            selection = sum(int(bool(result[decoder[str(i+1)]])) << i for i in range(3))
            for code, pin in enumerate([15, 14, 13]):
                if decoder[str(pin)] not in result:
                    result[decoder[str(pin)]] = not (enabled and selection == code)
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
        # This exercises physical pin declarations, not a parallel address-mask implementation.
        for address in range(65536):
            inputs = {f'A{i}': bool(address & (1 << i)) for i in range(16)}
            inputs.update(CS_ATTR_MODE=False, CS_INH_EXT=False)
            result = evaluate(self.manifest, inputs)
            selected = address & 0xFFF0 == 0xFEE0
            self.assertEqual(bool(result['CS_IO_HIT']), selected, hex(address))
            self.assertEqual(bool(result['CS_RAM_INH']), selected, hex(address))
            self.assertEqual(not result['CS_Y0_N'], selected and address & 7 == 0)
            self.assertEqual(not result['CS_Y1_N'], selected and address & 7 == 1)
            self.assertEqual(not result['CS_Y2_N'], selected and address & 7 == 2)
        for address in [0x0000, 0x3FFF, 0x4000, 0x430C, 0x7FFF, 0x8000, 0xFEE0, 0xFFFF]:
            for mode in (False, True):
                for external in (False, True):
                    inputs = {f'A{i}': bool(address & (1 << i)) for i in range(16)}
                    inputs.update(CS_ATTR_MODE=mode, CS_INH_EXT=external)
                    result = evaluate(self.manifest, inputs)
                    self.assertEqual(bool(result['CS_RAM_INH']), external or (
                        address & 0xFFF0 == 0xFEE0) or (mode and 0x4000 <= address < 0x8000))

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
