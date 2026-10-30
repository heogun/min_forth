"""Host-side contracts; guest execution is covered by run.py integration runs."""
import struct
import unittest

from cases import (basic_cases, cells, crc16, diagnostic_cases, extended_cases, mandelbrot_cases,
                   mandelbrot_reference, sources, trunc32)
from run import validate
from compare import compare
import copy


class SuiteTests(unittest.TestCase):
    def test_reference_vectors(self):
        cases = {c.name: c for c in basic_cases()}
        self.assertEqual(sum(cases["sieve"].expected), 172)
        self.assertEqual(struct.unpack("<H", cases["fib"].expected)[0], 8)
        bubble = cases["bubble"].expected
        values = list(struct.unpack("<32H", bubble))
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), 32)
        self.assertEqual(len(cases["matrix"].expected), 32)

    def test_source_protocol(self):
        for case in [*basic_cases(), *extended_cases(), *mandelbrot_cases(), *diagnostic_cases()]:
            with self.subTest(case=case.name):
                minimum, forth = sources(case)
                self.assertEqual(minimum.count("call 0xdf00"), 1)
                self.assertEqual(minimum.count("call 0xdf10"), 1)
                self.assertTrue(all(len(line) <= 46 for line in forth.splitlines()))
                self.assertTrue(forth.isascii())
                self.assertNotIn('"', forth)
                self.assertNotIn("%", minimum)  # Min has no remainder operator.
                for line in forth.splitlines():
                    self.assertNotIn(line.split()[-1].upper(), ("VARIABLE", "CONSTANT", ":"))

    def test_crc_check_vector(self):
        self.assertEqual(crc16(b"123456789"), 0x4b37)
        self.assertEqual(crc16(b""), 0xffff)

    def test_mandelbrot_fixed_point_contract(self):
        self.assertEqual([trunc32(n) for n in [-65, -32, -31, 0, 31, 32, 65]],
                         [-2, -1, 0, 0, 0, 1, 2])
        result = mandelbrot_reference()
        self.assertEqual(len(result), 192)
        self.assertEqual(max(result), 24)
        self.assertLess(min(result), 24)
        # On the cy=0 row c=-2 does not escape within the budget.
        self.assertEqual(result[6*16], 24)
        # Deterministic integer reference, independent of host FP behavior.
        self.assertEqual(result, mandelbrot_reference())

    def test_cells_wrap_and_little_endian(self):
        self.assertEqual(cells([0, 0xffff, -1, 0x1234]), b"\0\0\xff\xff\xff\xff\x34\x12")

    def fixture(self):
        case = next(c for c in basic_cases() if c.name == "fib")
        ram = bytearray(0x10000)
        ram[case.address:case.address+len(case.expected)] = case.expected
        ram[15:17] = b"\0\x81"
        ram[0x7c:0x80] = b"\0\0\0\x28"
        timing = dict(start_cycle=10, end_cycle=30, raw_cycles=20,
                      start_data_sp=254, data_sp=254,
                      start_return_sp=240, return_sp=240)
        return case, ram, timing

    def test_validator_accepts_correct_output_and_state(self):
        case, ram, timing = self.fixture()
        validate(case, "forth", timing, ram)
        self.assertEqual(timing["dictionary_bytes"], 256)

    def test_validator_rejects_wrong_output(self):
        case, ram, timing = self.fixture()
        ram[case.address] ^= 1
        with self.assertRaisesRegex(ValueError, "wrong output"):
            validate(case, "forth", timing, ram)

    def test_validator_rejects_stack_leaks_even_when_output_is_correct(self):
        for key in ["start_data_sp", "data_sp", "return_sp"]:
            case, ram, timing = self.fixture()
            timing[key] -= 2
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "stack"):
                validate(case, "forth", timing, ram)

    def test_validator_rejects_bad_loop_compile_and_dictionary_state(self):
        for address in [0x7c, 0xe, 0x34, 0x10]:
            case, ram, timing = self.fixture()
            ram[address] = 0xff
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate(case, "forth", timing, ram)

    def test_validator_rejects_inconsistent_cycles_and_truncated_ram(self):
        case, ram, timing = self.fixture()
        timing["raw_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate(case, "forth", timing, ram)
        with self.assertRaisesRegex(ValueError, "RAM dump"):
            validate(case, "forth", timing, ram[:-1])

    def test_diagnostic_workloads_have_independent_results(self):
        self.assertEqual([struct.unpack('<H', c.expected)[0] for c in diagnostic_cases()],
                         [2080, 2208, 192, 0])

    def test_phase_partition_and_compiled_size(self):
        case, ram, timing = self.fixture()
        timing.update(phases=dict(boot=1, input=3, compile=6, execute=20),
                      memory=dict(boot_dictionary_bytes=128))
        validate(case, "forth", timing, ram)
        self.assertEqual(timing['compiled_dictionary_bytes'], 128)
        timing['phases']['compile'] += 1
        with self.assertRaisesRegex(ValueError, "phase totals"):
            validate(case, "forth", timing, ram)

    def test_validator_rejects_wrong_execution_phase(self):
        case, ram, timing = self.fixture()
        timing.update(phases=dict(boot=1, input=3, compile=7, execute=19),
                      memory=dict(boot_dictionary_bytes=128))
        with self.assertRaisesRegex(ValueError, "execution phase"):
            validate(case, "forth", timing, ram)

    def comparison_fixture(self):
        return dict(status='passed', control_sha256=dict(lsb='a', msb='b', hsb='c'),
                    input_mode='buffered', results=[dict(case='test', parameters=dict(n=1),
                    expected_sha256='result', languages=dict(forth=dict(verified=True,
                    source_sha256='source', measurements=[dict(raw_cycles=100,
                    dictionary_bytes=1000, compiled_dictionary_bytes=500,
                    phases=dict(compile=100, execute=100))])))])

    def test_comparison_reports_clocks_code_size_and_compiler_delta(self):
        old = self.comparison_fixture()
        new = copy.deepcopy(old)
        m = new['results'][0]['languages']['forth']['measurements'][0]
        m.update(raw_cycles=80, dictionary_bytes=990, compiled_dictionary_bytes=490,
                 phases=dict(compile=90, execute=80))
        row = compare(old, new)[0]
        self.assertEqual(row['delta_cycles'], -20)
        self.assertAlmostEqual(row['delta_percent'], -20)
        self.assertEqual(row['dictionary_bytes_delta'], -10)
        self.assertEqual(row['compiled_dictionary_bytes_delta'], -10)
        self.assertEqual(row['phase_deltas']['compile'], -10)

    def test_comparison_rejects_failed_or_different_hardware_or_workload(self):
        old = self.comparison_fixture()
        variants = []
        new = copy.deepcopy(old); new['status'] = 'failed'; variants.append(new)
        new = copy.deepcopy(old); new['control_sha256']['lsb'] = 'other'; variants.append(new)
        new = copy.deepcopy(old); new['input_mode'] = 'timed'; variants.append(new)
        new = copy.deepcopy(old); new['results'][0]['parameters']['n'] = 2; variants.append(new)
        new = copy.deepcopy(old); new['results'][0]['expected_sha256'] = 'wrong'; variants.append(new)
        for variant in variants:
            with self.assertRaises(ValueError):
                compare(old, variant)

    def test_comparison_rejects_unverified_or_unstable_measurements(self):
        old = self.comparison_fixture()
        new = copy.deepcopy(old)
        lang = new['results'][0]['languages']['forth']
        lang['verified'] = False
        with self.assertRaises(ValueError):
            compare(old, new)
        lang['verified'] = True
        lang['measurements'].append(dict(raw_cycles=101))
        with self.assertRaises(ValueError):
            compare(old, new)

    def test_comparison_flags_changed_sources(self):
        old = self.comparison_fixture()
        new = copy.deepcopy(old)
        new['results'][0]['languages']['forth']['source_sha256'] = 'edited'
        self.assertTrue(compare(old, new)[0]['source_changed'])


if __name__ == "__main__":
    unittest.main()
