#!/usr/bin/env python3
"""ABORT-quote state/recovery regressions using actual MinOS/Forth ROMs."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
ROM_DIR = ROOT / "../minforth/build-p1"


def run(lines):
    for line in lines:
        if len(line) > 46:
            raise ValueError(f"test line exceeds editor limit: {line}")
    with tempfile.TemporaryDirectory(prefix="abort-", dir=ROOT / "target") as tmp:
        ram_path = Path(tmp) / "ram.bin"
        payload = ("minforth\n" + "\n".join(lines) + "\n").encode().hex()
        result = subprocess.run([
            str(ROOT / "target/release/minredux"), "run", "--rom-dir", str(ROM_DIR),
            "--uart-hex", payload, "--uart-after", "200000", "--cycles", "6000000",
            "--no-output", "--text", "--dump-ram", str(ram_path),
        ], capture_output=True, text=True, check=True, timeout=30)
        return ram_path.read_bytes(), result.stdout


def cell(ram, address):
    return int.from_bytes(ram[address:address+2], "little")


def dictionary(ram):
    result, pointer = {}, cell(ram, 0x11)
    seen = set()
    while pointer:
        if pointer in seen or not 0x8000 <= pointer < 0xf000:
            raise AssertionError("corrupt dictionary chain")
        seen.add(pointer)
        n = ram[pointer] & 31
        name = ram[pointer+5:pointer+5+n].decode("ascii")
        result[name] = cell(ram, pointer+3)
        pointer = cell(ram, pointer+1)
    return result


class AbortQuoteTests(unittest.TestCase):
    def clean(self, ram):
        self.assertEqual(ram[0], 0xfe, "data stack must be empty")
        for address in [0xe, 0x34, 0x72, 0x73]:
            self.assertEqual(ram[address], 0, f"compiler state at {address:02x}")
        self.assertEqual(ram[0x7c:0x80], b"\0\0\0\x28", "loop frames must be empty")

    def test_false_pops_only_flag_and_continues(self):
        ram, screen = run([': t ABORT" FALSEMSG" 9 ;', '77 0 t + 57344 !'])
        self.assertEqual(cell(ram, 0xe000), 86)
        self.assertEqual(screen.count("FALSEMSG"), 1, "message should only appear in input echo")
        self.clean(ram)

    def test_true_prints_discards_line_and_recovers(self):
        ram, screen = run([': t ABORT" MiXeD msg" ;',
                           '55 65535 t 123 57344 !', '7 57346 !'])
        self.assertEqual(cell(ram, 0xe000), 0)
        self.assertEqual(cell(ram, 0xe002), 7)
        self.assertEqual(screen.count("MiXeD msg"), 2)
        self.clean(ram)

    def test_empty_message(self):
        ram, _ = run([': t ABORT" " ;', '1 t 88 57344 !', '9 57346 !'])
        self.assertEqual(cell(ram, 0xe000), 0)
        self.assertEqual(cell(ram, 0xe002), 9)
        self.clean(ram)

    def test_false_empty_message_skips_to_following_code(self):
        ram, _ = run([': t 0 ABORT" " 13 ;', 't 57344 !'])
        self.assertEqual(cell(ram, 0xe000), 13)
        self.clean(ram)

    def test_nested_calls_return_and_loop_stacks_are_abandoned(self):
        ram, screen = run([': trip 1 ABORT" NESTMSG" ;',
                           ': inner 42 >R trip R> DROP ;',
                           ': outer 3 0 DO 2 0 DO inner LOOP LOOP ;',
                           '99 outer 88 57346 !',
                           ': sum 0 10 0 DO I + LOOP ;', 'sum 57344 !'])
        self.assertEqual(cell(ram, 0xe000), 45)
        self.assertEqual(cell(ram, 0xe002), 0)
        self.assertEqual(screen.count("NESTMSG"), 2)
        self.clean(ram)

    def test_compilation_abort_rolls_back_partial_header_and_control_state(self):
        setup = [': trip 1 ABORT" BUILDMSG" ; IMMEDIATE']
        before, _ = run(setup)
        ram, screen = run(setup + [': broken IF trip', ': ok 17 ;', 'ok 57344 !'])
        self.assertNotIn("BROKEN", dictionary(ram))
        self.assertIn("TRIP", dictionary(ram))
        self.assertEqual(cell(ram, 0xe000), 17)
        # Only header (5+2), literal (13) and RTS (1) for OK may remain.
        self.assertEqual(cell(ram, 15) - cell(before, 15), 21)
        self.assertEqual(screen.count("BUILDMSG"), 2)
        self.clean(ram)

    def test_compilation_abort_clears_pending_do_leave_patches(self):
        ram, _ = run([': trip 1 ABORT" LEAVEMSG" ; IMMEDIATE',
                      ': broken 3 0 DO LEAVE trip',
                      ': ok 0 4 0 DO I + LOOP ;', 'ok 57344 !'])
        self.assertNotIn("BROKEN", dictionary(ram))
        self.assertEqual(cell(ram, 0xe000), 6)
        self.clean(ram)

    def test_flag_with_only_high_byte_set_is_true(self):
        ram, screen = run([': t ABORT" HIGHMSG" ;', '256 t 99 57344 !', '21 57346 !'])
        self.assertEqual(cell(ram, 0xe000), 0)
        self.assertEqual(cell(ram, 0xe002), 21)
        self.assertEqual(screen.count("HIGHMSG"), 2)
        self.clean(ram)

    def test_false_string_crosses_page_boundary(self):
        message = '0123456789abcdefghij'
        ram, screen = run(['34020 HERE !', f': t 0 ABORT" {message}" 27 ;', 't 57344 !'])
        start = ram.index(message.encode(), dictionary(ram)['T'])
        self.assertGreater((start & 255) + len(message), 256)
        self.assertEqual(cell(ram, 0xe000), 27)
        self.assertEqual(screen.count(message), 1)
        self.clean(ram)

    def test_missing_quote_rolls_back_definition(self):
        ram, screen = run([': broken 1 ABORT" unfinished', ': ok 19 ;', 'ok 57344 !'])
        self.assertNotIn("BROKEN", dictionary(ram))
        self.assertEqual(cell(ram, 0xe000), 19)
        self.assertIn("compile/closing quote required", screen)
        self.clean(ram)

    def test_interpretation_use_is_rejected_without_dictionary_damage(self):
        ram, _ = run([': ok 23 ;', '44 ABORT" direct" 99 57346 !', 'ok 57344 !'])
        self.assertEqual(cell(ram, 0xe000), 23)
        self.assertEqual(cell(ram, 0xe002), 0)
        self.clean(ram)

    def test_base_and_completed_dictionary_and_variables_survive(self):
        ram, _ = run(['VARIABLE v', '42 v !', ': trip 1 ABORT" KEEPMSG" ;',
                      'HEX', 'trip', 'BASE @ E000 !', 'DECIMAL', 'v @ 57346 !'])
        self.assertEqual(cell(ram, 0xe000), 16)
        self.assertEqual(cell(ram, 0xe002), 42)
        self.assertIn("TRIP", dictionary(ram))
        self.clean(ram)

    def test_multiple_abort_cycles_and_new_definitions(self):
        ram, screen = run([': trip 1 ABORT" AGAINMSG" ;', 'trip', 'trip',
                           ': t 0 3 0 DO I + LOOP ;', 't 57344 !'])
        self.assertEqual(cell(ram, 0xe000), 3)
        self.assertEqual(screen.count("AGAINMSG"), 3)
        self.clean(ram)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom-dir", type=Path, default=ROM_DIR)
    args, rest = parser.parse_known_args()
    ROM_DIR = args.rom_dir.resolve()
    unittest.main(argv=[__file__, *rest])
