import hashlib
import json
import unittest

from cad_sexpr import Atom, parse, quoted, replace
from prepare_cad import HERE, ROOT, PROJECT, copper_signature, hierarchy, symbol_name


CAD = HERE / 'cad'
ORIGINAL = ROOT / 'minimal64/Revision 1.4 Redux/KiCAD9'


def pin_signature(symbol):
    def tree(node):
        if isinstance(node, Atom):
            return node.value
        return tuple(tree(c) for c in node.children)
    return sorted(tree(n) for n in symbol.walk() if n.name == 'pin')


class SExpressionTests(unittest.TestCase):
    def test_escaped_string_and_nested_lists(self):
        text = r'(root (property "Value" "a \"quote\" and (parentheses)") (at 1 2))'
        node = parse(text)
        self.assertEqual(node.one('at').value(), '1')
        self.assertEqual(node.one('property').value(2), 'a "quote" and (parentheses)')

    def test_edits_preserve_unmodified_spans(self):
        text = '(root\n  (net 1 "old")\n  (pad "1" thru_hole))'
        atom = parse(text).one('net').children[2]
        self.assertEqual(replace(text, [quoted(atom, 'new')]), text.replace('"old"', '"new"'))

    def test_invalid_and_overlapping_edits_fail(self):
        for text in ('(root', '(root))', '(root) (second)'):
            with self.assertRaises(ValueError):
                parse(text)
        with self.assertRaises(ValueError):
            replace('abcdef', [(0, 4, 'x'), (2, 5, 'y')])


class PreparedCADTests(unittest.TestCase):
    def test_frozen_symbol_pins_match_all_embedded_definitions(self):
        library = parse((CAD / 'Redux.kicad_sym').read_text())
        symbols = {s.value(): s for s in library.nodes('symbol')}
        self.assertEqual(len(symbols), 38)
        for _, root in hierarchy(CAD).values():
            for symbol in root.one('lib_symbols').nodes('symbol'):
                local = symbol.value().split(':')[1]
                self.assertEqual(pin_signature(symbol), pin_signature(symbols[local]))

    def test_no_drc_exclusions_or_ttf_dependencies(self):
        project = json.loads((CAD / f'{PROJECT}.kicad_pro').read_text())
        self.assertEqual(project['board']['design_settings']['drc_exclusions'], [])
        root = parse((CAD / f'{PROJECT}.kicad_pcb').read_text())
        for text in root.nodes('gr_text'):
            self.assertFalse(text.nodes('render_cache'))
            self.assertFalse(text.one('effects').one('font').nodes('face'))

    def test_copper_and_pad_geometry_matches_baseline(self):
        metadata = json.loads((CAD / 'baseline-invariants.json').read_text())
        actual = copper_signature((CAD / f'{PROJECT}.kicad_pcb').read_text())
        self.assertEqual(actual, metadata['copper_and_pad_geometry_sha256'])

    @unittest.skipUnless(ORIGINAL.exists(), 'Original reference checkout not installed')
    def test_original_sources_and_symbol_pins_unchanged(self):
        metadata = json.loads((CAD / 'baseline-invariants.json').read_text())
        for name, expected in metadata['source_sha256'].items():
            self.assertEqual(hashlib.sha256((ORIGINAL / name).read_bytes()).hexdigest(), expected)
        library = parse((CAD / 'Redux.kicad_sym').read_text())
        symbols = {s.value(): s for s in library.nodes('symbol')}
        for _, root in hierarchy(ORIGINAL).values():
            for symbol in root.one('lib_symbols').nodes('symbol'):
                self.assertEqual(pin_signature(symbol), pin_signature(symbols[symbol_name(symbol.value())]))

    @unittest.skipUnless(ORIGINAL.exists(), 'Original reference checkout not installed')
    def test_no_new_ignored_rules(self):
        old = json.loads((ORIGINAL / f'{PROJECT}.kicad_pro').read_text())
        new = json.loads((CAD / f'{PROJECT}.kicad_pro').read_text())
        self.assertEqual(old['board']['design_settings']['rule_severities'],
                         new['board']['design_settings']['rule_severities'])
        self.assertEqual(old['erc'], new['erc'])


if __name__ == '__main__':
    unittest.main()
