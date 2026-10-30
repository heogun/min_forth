import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('check_kicad', Path(__file__).with_name('check_kicad.py'))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_erc_summary_does_not_hide_warnings(self):
        row = {'severity': 'warning', 'type': 'lib_symbol_mismatch'}
        result = audit.summarize({'sheets': [{'violations': [row, row]}]}, 'erc')
        self.assertEqual(result['violations'], [dict(
            state='active', severity='warning', type='lib_symbol_mismatch', count=2)])

    def test_drc_separates_exclusions_parity_and_unconnected(self):
        row = {'severity': 'warning', 'type': 'text_height', 'excluded': True}
        report = {'violations': [row], 'unconnected_items': [],
                  'schematic_parity': [{'severity': 'warning', 'type': 'net_conflict'}]}
        result = audit.summarize(report, 'drc')
        self.assertEqual(result['violations'][0]['state'], 'excluded')
        self.assertEqual(result['schematic_parity'][0]['state'], 'active')
        self.assertEqual(result['unconnected_items'], [])

    def test_missing_report_section_is_not_a_pass(self):
        with self.assertRaises(KeyError):
            audit.summarize({'violations': []}, 'drc')

    def test_library_table_preserves_custom_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project, libraries = root / 'project', root / 'libraries'
            project.mkdir()
            libraries.mkdir()
            for name in ('Custom', 'Package_DIP'):
                (libraries / f'{name}.pretty').mkdir()
            table = project / 'fp-lib-table'
            original = '(fp_lib_table\n(lib (name "Custom")(uri "${KIPRJMOD}/custom.pretty"))\n)'
            table.write_text(original)
            self.assertEqual(audit.add_footprint_libraries(project, libraries), 1)
            text = table.read_text()
            self.assertIn('${KIPRJMOD}/custom.pretty', text)
            self.assertEqual(text.count('(name "Custom")'), 1)
            self.assertIn('(name "Package_DIP")', text)
            self.assertEqual(audit.add_footprint_libraries(project, libraries), 0)

    def test_empty_library_installation_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                audit.add_footprint_libraries(Path(folder), Path(folder))

    def test_fingerprint_covers_nested_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'nested').mkdir()
            file = root / 'nested/test.kicad_sch'
            file.write_text('before')
            before = audit.fingerprint(root)
            self.assertIn('nested/test.kicad_sch', before)
            file.write_text('after')
            self.assertNotEqual(audit.fingerprint(root), before)


if __name__ == '__main__':
    unittest.main()
