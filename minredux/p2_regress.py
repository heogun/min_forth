#!/usr/bin/env python3
"""Check P2 generated machine code and RAM results, not echoed input."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.symbols = json.loads(Path('../minforth/build/minforth.symbols.json').read_text())
        lines = [
            ': chain 1- ;', ': tail chain ;',
            ': branch IF chain THEN ;',
            ': literal chain 5 ;', ': early chain EXIT ;',
            ': rr 42 >R R> ;', ': rx 57088 EXECUTE ;',
            ': rt >R ;', ': rf R@ ;',
            ': d DROP ;', ': idx I ;', ': add + ;',
            ': inc 1+ ;', ': cf C@ ;',
            'rr 57344 !', '7 tail 57346 !',
            '9 0 branch 57348 !', '9 1 branch 57350 !',
            '65535 inc 57352 !', '65535 1 add 57354 !',
            '255 57599 C! 57599 cf 57356 !',
            '11 256 1 - 57358 ! 57360 !',
            '255 1 add 57362 !', '255 inc 57364 !',
            '65280 255 OR 57366 !', '65280 255 AND 57368 !',
            '65535 255 XOR 57370 !', '256 255 < 57372 !',
            '255 256 < 57374 !', '256 256 = 57376 !',
            '4660 57599 ! 57599 @ 57378 !',
            '65535 57599 ! 1 57599 +! 57599 @ 57380 !',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'ram.bin'
            subprocess.run([
                './target/release/minredux', 'run', '--rom-dir', '../minforth/build',
                '--cycles', '6000000', '--no-output', '--uart-after', '200000',
                '--uart-hex', ('minforth\n' + '\n'.join(lines) + '\n').encode().hex(),
                '--dump-ram', str(dump),
            ], check=True, capture_output=True)
            cls.ram = dump.read_bytes()
        cls.words = {}
        ptr = cls.cell(cls.symbols['zLATEST'])
        end = cls.cell(cls.symbols['zHERE'])
        while ptr:
            length = cls.ram[ptr] & 0x7f
            name = cls.ram[ptr+5:ptr+5+length].decode('ascii').lower()
            xt = cls.cell(ptr+3)
            cls.words[name] = (xt, cls.ram[xt:end])
            end, ptr = ptr, cls.cell(ptr+1)

    @classmethod
    def cell(cls, address):
        return int.from_bytes(cls.ram[address:address+2], 'little')

    def test_tail_and_branch_target(self):
        chain = self.words['chain'][0].to_bytes(2, 'little')
        self.assertEqual(self.words['tail'][1], b'\x66' + chain)
        xt, body = self.words['branch']
        self.assertEqual(body[-4:], b'\x66' + chain + b'\x6b')
        self.assertEqual(int.from_bytes(body[4:6], 'little'), xt + len(body)-1)

    def test_bytes_after_call_disable_tail(self):
        for name in ['literal', 'early']:
            self.assertEqual(self.words[name][1][0], 0x69)
            self.assertEqual(self.words[name][1][-1], 0x6b)

    def test_frame_sensitive_calls_keep_rts(self):
        for name, primitive in [('rr', 'wFROMR'), ('rx', 'wEXEC'),
                                ('rt', 'wTOR'), ('rf', 'wRFETCH')]:
            expected = b'\x69' + self.symbols[primitive].to_bytes(2, 'little') + b'\x6b'
            self.assertEqual(self.words[name][1][-4:], expected)

    def test_inline_bytes_match_primitive(self):
        for name, primitive in [('d', 'wDROP'), ('idx', 'wI'), ('add', 'wADD'),
                                ('inc', 'wINC'), ('cf', 'wCFETCH')]:
            body = self.words[name][1]
            start = self.symbols[primitive]
            self.assertEqual(body[-1], 0x6b)
            self.assertEqual(body, self.ram[start:start+len(body)])

    def test_execution_results(self):
        expected = [42, 6, 9, 8, 0, 0, 255, 255, 11, 256, 256,
                    65535, 0, 65280, 0, 65535, 65535, 4660, 0]
        self.assertEqual([self.cell(0xe000 + i*2) for i in range(len(expected))],
                         expected)
        self.assertEqual(self.ram[self.symbols['zSP']], 0xfe)
        self.assertEqual(self.cell(self.symbols['zLSTKP']), 0x2800)


if __name__ == '__main__':
    unittest.main()
