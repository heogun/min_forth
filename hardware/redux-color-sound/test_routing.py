import io
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from check_kicad import HERE, ROOT, PROJECT
from fetch_router import safe_members
from routing_checks import preservation_report
from route_board import adopt


def minimal_board(width='0.25', position='0 0', extra=''):
    return f'''(kicad_pcb (net 1 "CLK")
      (segment (start 0 0) (end 1 1) (width {width}) (layer "F.Cu") (net 1) (uuid "wire"))
      (footprint "Package_DIP:DIP-14" (at {position}) (layer "F.Cu")
        (property "Reference" "U1") (property "Value" "74HC00")
        (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8)
          (layers "*.Cu" "*.Mask") (net 1 "CLK"))) {extra})'''


class RoutingSafetyTests(unittest.TestCase):
    def test_additive_route_preserves_original(self):
        old = minimal_board()
        new = minimal_board(width='0.250000', extra='''(segment (start 1 1) (end 2 2)
          (width 0.25) (layer "B.Cu") (net 1) (uuid "new"))''')
        result = preservation_report(old, new)
        self.assertTrue(result['preserved'])
        self.assertEqual(result['added_copper_count'], 1)
        self.assertEqual(result['before_copper_sha256'], result['after_protected_copper_sha256'])

    def test_changed_clock_copper_is_rejected(self):
        result = preservation_report(minimal_board(), minimal_board(width='0.2'))
        self.assertFalse(result['preserved'])
        self.assertEqual(result['changed_copper'], ['wire'])

    def test_component_movement_is_rejected(self):
        result = preservation_report(minimal_board(), minimal_board(position='0.1 0'))
        self.assertFalse(result['preserved'])
        self.assertEqual(result['changed_footprints'], ['U1'])

    def test_unsafe_archive_paths_are_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as tar:
            info = tarfile.TarInfo('../outside')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        buffer.seek(0)
        with tempfile.TemporaryDirectory() as folder, tarfile.open(fileobj=buffer) as tar:
            with self.assertRaises(ValueError):
                safe_members(tar, Path(folder))

    def test_incomplete_candidate_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, work = root / 'project', root / 'work'
            source.mkdir()
            (work / 'candidate').mkdir(parents=True)
            (work / 'checked').mkdir()
            name = PROJECT+'.kicad_pcb'
            old = minimal_board()
            (source / name).write_text(old)
            (work / 'candidate' / name).write_text(old)
            checksum = hashlib.sha256(old.encode()).hexdigest()
            (work / 'before.json').write_text(json.dumps({'source_sha256': checksum}))
            (work / 'checked/summary.json').write_text(json.dumps({
                'source_sha256': {name: checksum}}))
            (work / 'checked/erc.json').write_text(json.dumps({'sheets': [{'violations': []}]}))
            (work / 'checked/drc.json').write_text(json.dumps({
                'violations': [], 'unconnected_items': [{'type': 'unconnected_items'}],
                'schematic_parity': []}))
            with self.assertRaisesRegex(ValueError, 'unconnected'):
                adopt(source, work)
            self.assertEqual((source / name).read_text(), old)

    @unittest.skipUnless((HERE / 'integrated/routing-report.json').exists(), 'Routing not finalized')
    def test_final_board_preserves_pre_routing_copper_and_placement(self):
        report = json.loads((HERE / 'integrated/routing-report.json').read_text())
        original = subprocess.run(['git', 'show', report['source_commit']+':'+
            'hardware/redux-color-sound/integrated/'+PROJECT+'.kicad_pcb'],
            cwd=ROOT, check=True, capture_output=True, text=True).stdout
        current = (HERE / 'integrated' / (PROJECT+'.kicad_pcb')).read_text()
        actual = preservation_report(original, current)
        self.assertTrue(actual['preserved'], actual)
        self.assertEqual(actual['protected_copper_count'], 4664)
        self.assertEqual(actual['protected_footprint_count'], 190)


if __name__ == '__main__':
    unittest.main()
