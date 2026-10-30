#!/usr/bin/env python3
"""Run paired Min/Forth benchmarks in private ROM images (stdlib only)."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import signal

from cases import basic_cases, diagnostic_cases, extended_cases, mandelbrot_cases, sources
from compare import compare

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "minimal64/Revision 1.4 Redux/FLASH Images"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"minforth/tools/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True,
                          text=True, **kwargs)


def insert(flash, name, dest, data, fs):
    entries, old_end = fs.parse(flash)
    entries = [e for e in entries if e[0] != name.encode()]
    entries.append([name.encode(), dest, data])
    payload = fs.build(entries)
    end = fs.FS_START + len(payload)
    if end > len(flash):
        raise ValueError("FLASH filesystem overflow")
    flash = bytearray(flash)
    flash[fs.FS_START:end] = payload
    if end < old_end:
        flash[end:old_end] = b"\xff" * (old_end-end)
    return bytes(flash)


def validate(case, language, measurement, ram):
    if len(ram) != 0x10000:
        raise ValueError("RAM dump must be exactly 64 KiB")
    actual = ram[case.address:case.address + len(case.expected)]
    if actual != case.expected:
        mismatches = [(i, a, b) for i, (a, b) in enumerate(zip(actual, case.expected)) if a != b]
        raise ValueError(f"{case.name}/{language}: wrong output {mismatches[:8]}")
    if measurement["end_cycle"] <= measurement["start_cycle"]:
        raise ValueError("invalid timing interval")
    if measurement["raw_cycles"] != measurement["end_cycle"] - measurement["start_cycle"]:
        raise ValueError("inconsistent cycle counters")
    if measurement["start_return_sp"] != measurement["return_sp"]:
        raise ValueError(f"{case.name}/{language}: unbalanced hardware return stack")
    if language == "forth":
        if measurement["start_data_sp"] != 0xfe or measurement["data_sp"] != 0xfe:
            raise ValueError(f"{case.name}: unbalanced Forth stack")
        here = int.from_bytes(ram[0x0f:0x11], "little")
        if not 0x8000 <= here < 0xd000:
            raise ValueError("Forth dictionary overlaps benchmark workspace")
        if ram[0x7c:0x80] != b"\0\0\0\x28":
            raise ValueError(f"{case.name}: unbalanced Forth loop frames")
        if ram[0xe] != 0 or ram[0x34] != 0:
            raise ValueError("Forth compilation did not finish cleanly")
        measurement["dictionary_bytes"] = here - 0x8000
    if "phases" in measurement:
        phases = measurement["phases"]
        if sum(phases.values()) != measurement["end_cycle"]:
            raise ValueError("phase totals do not cover the entire run")
        if phases["execute"] != measurement["raw_cycles"]:
            raise ValueError("execution phase disagrees with timing hooks")
        if any(n < 0 for n in phases.values()):
            raise ValueError("negative phase duration")
        if language == "forth":
            measurement["compiled_dictionary_bytes"] = measurement["dictionary_bytes"] - measurement["memory"]["boot_dictionary_bytes"]
            if measurement["compiled_dictionary_bytes"] < 0:
                raise ValueError("dictionary shrank below its boot checkpoint")
            span = measurement["memory"].get("dictionary_written_span_bytes")
            if span is not None and span != measurement["dictionary_bytes"]:
                raise ValueError("dictionary write high-water disagrees with HERE")
            if phases["compile"] == 0 or phases["input"] == 0:
                raise ValueError("missing Forth compilation/input observation")
        elif phases["tokenize"] == 0 or measurement["memory"].get("token_bytes", 0) == 0:
            raise ValueError("missing Min tokenizer observation")


def profile_config(language, symbols, code_bytes, os_symbols):
    names = {}
    if language == "forth":
        names.update(app_entry="wBoot", app_ready="wRepl", word="nf_word", next="nf_next",
                     parse="nf_parse", find="nf_find", emit="nf_cbyte", state="zSTATE",
                     token="zTOK", token_len="zTOKLEN", here="zHERE", data_sp="zSP", loop_top="zLSTKP")
    else:
        names.update(app_ready="Block", loader="Loader", tokenizer="Tokenizer",
                     source_end_ptr="z_PtrD", token_end_ptr="dst")
    values = {key: symbols[name] for key, name in names.items()}
    values.update(prompt=os_symbols["OS_Prompt"], readline=os_symbols["OS_ReadLine"],
                  native_load=os_symbols["OS_LoadFile"])
    if language == "min":
        values["app_entry"] = 0x1000
    values["code_bytes"] = code_bytes
    return "language " + language + "\n" + "".join(f"{key} {value:04x}\n" for key, value in sorted(values.items()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--control-rom", type=Path, default=REFERENCE)
    p.add_argument("--case", action="append", help="select case(s); default all implemented")
    p.add_argument("--stage", type=int, choices=[1, 2, 3], default=3,
                   help="include cases up to this implementation stage (default 3)")
    p.add_argument("--repeat", type=int, default=2)
    p.add_argument("--max-cycles", type=int, default=300_000_000)
    p.add_argument("--host-timeout", type=int, default=180, help="host seconds per guest execution (default 180)")
    p.add_argument("--out", type=Path, help="new run directory; existing paths refused")
    p.add_argument("--diagnostics", action="store_true", help="also run call/stack/DO/parser micro workloads")
    p.add_argument("--baseline", type=Path, help="compare with a passed same-ROM results.json")
    p.add_argument("--verify-profile", action="store_true", help="also run each case without observers and compare clocks/all RAM")
    args = p.parse_args()
    if args.repeat < 1 or args.max_cycles < 1 or args.host_timeout < 1:
        p.error("repeat, max-cycles and host-timeout must be positive")
    cases = list(basic_cases())
    if args.stage >= 2:
        cases.extend(extended_cases())
    if args.stage >= 3:
        cases.extend(mandelbrot_cases())
    if args.diagnostics:
        cases.extend(diagnostic_cases())
    if args.case:
        unknown = set(args.case) - {c.name for c in cases}
        if unknown:
            p.error(f"unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c.name in args.case or c.name == "empty"]
    base = ROOT / "benchmarks/results"
    base.mkdir(exist_ok=True)
    if args.out:
        out = args.out.resolve()
        protected = [REFERENCE.parent.resolve(), (ROOT / "minforth/build").resolve(),
                     (ROOT / "minforth/build-isa-fixes-v1").resolve(), (ROOT / "roms").resolve()]
        if any(out == path or path in out.parents for path in protected):
            p.error("output must not be inside reference ROMs or existing Forth/ROM bundles")
        if out.exists():
            p.error(f"output directory already exists: {out}")
        out.mkdir(parents=True, exist_ok=False)
    else:
        out = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    print(f"Artifacts: {out}", flush=True)
    report = {"schema": 2, "stage": args.stage, "measurement": "raw hook-entry to hook-entry cycles; no subtraction",
              "max_cycles": args.max_cycles, "host_timeout_seconds": args.host_timeout,
              "repeat": args.repeat, "diagnostics": args.diagnostics,
              "observer_verification_requested": args.verify_profile, "results": [], "status": "running"}
    result_path = out / "results.json"
    def save():
        result_path.write_text(json.dumps(report, indent=2) + "\n")
    save()
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"terminated by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        command(["cargo", "build", "--release", "--example", "benchmark"], cwd=ROOT / "minredux")
        # Always rebuild current kernel, never reuse a potentially stale flash.
        command([sys.executable, ROOT / "minforth/tools/build.py",
                 ROOT / "minforth/forth/kernel.fs", "minforth", "0x1000", "--out", out / "kernel"])
        sys.path.insert(0, str(ROOT / "minforth/tools"))
        build, fs = load_tool("build"), load_tool("fspatch")
        forth_symbols = json.loads((out / "kernel/minforth.symbols.json").read_text())
        forth_code = (out / "kernel/minforth.bin").read_bytes()
        if 0x1000 + len(forth_code) > forth_symbols["nfDefHere"]:
            raise ValueError("kernel overlaps compiler checkpoint RAM")
        min_source = (ROOT / "minimal64/Revision 1.4 Redux/Programs/asm/min.asm").read_text()
        min_symbols, emitted = {}, {}
        min_code, min_base = build.assemble(min_source, min_symbols, emitted)
        entries, _ = fs.parse((REFERENCE / "flash.bin").read_bytes())
        min_program = next(entry for entry in entries if entry[0] == b"min")
        if min_base != min_program[1] or len(min_code) != len(min_program[2]) or any(
                min_program[2][address-min_base] != value for address, value in emitted.items()):
            raise ValueError("Min source symbols do not describe the distributed executable")
        # Only unemitted #page padding differs (00 in distributed image, ff in
        # the flat assembler helper). Every explicitly emitted byte must match.
        (out / "min.symbols.json").write_text(json.dumps(min_symbols, indent=2, sort_keys=True) + "\n")
        os_source = (ROOT / "minimal64/Revision 1.4 Redux/Programs/asm/os.asm").read_text()
        os_symbols, os_emitted = {}, {}
        build.assemble(os_source, os_symbols, os_emitted)
        reference_flash = (REFERENCE / "flash.bin").read_bytes()
        if any(reference_flash[address] != value for address, value in os_emitted.items()):
            raise ValueError("MinOS symbols do not describe the distributed executable")
        (out / "os.symbols.json").write_text(json.dumps(os_symbols, indent=2, sort_keys=True) + "\n")
        configs = {"min": profile_config("min", min_symbols, len(min_code), os_symbols),
                   "forth": profile_config("forth", forth_symbols, len(forth_code), os_symbols)}
        hook_source = "#org 0xde00\nJPA 0xf003\n#org 0xdf00\nRTS\n#org 0xdf10\nRTS\n"
        hooks, address = build.assemble(hook_source)
        if address != 0xde00:
            raise ValueError("unexpected timing hook load address")
        controls = {n: (args.control_rom / n).read_bytes()
                    for n in ["ctrl_lsb.bin", "ctrl_msb.bin", "ctrl_hsb.bin"]}
        if any(len(data) != 0x80000 for data in controls.values()):
            raise ValueError("control ROMs must each be 512 KiB")
        report["control_sha256"] = {n: sha(b) for n, b in controls.items()}
        report["kernel_source_sha256"] = sha((ROOT / "minforth/forth/kernel.fs").read_bytes())
        report["kernel_defs_sha256"] = sha((ROOT / "minforth/forth/defs.inc").read_bytes())
        report["runner_sha256"] = sha((ROOT / "minredux/target/release/examples/benchmark").read_bytes())
        report["cases_sha256"] = sha((ROOT / "benchmarks/cases.py").read_bytes())
        report["min_source_sha256"] = sha(min_source.encode())
        report["min_program_sha256"] = sha(min_program[2])
        report["os_source_sha256"] = sha(os_source.encode())
        report["profile_symbols"] = {"min": min_symbols, "forth": forth_symbols, "os": os_symbols}
        report["input_mode"] = "buffered; uart_after=200000; no realtime throttle"
        for case in cases:
            pair = {"case": case.name, "stage": case.stage, "parameters": case.parameters,
                    "expected_sha256": sha(case.expected), "languages": {}}
            report["results"].append(pair)
            for language, source in zip(["min", "forth"], sources(case)):
                folder = out / case.name / language
                folder.mkdir(parents=True)
                (folder / ("source.min" if language == "min" else "source.fs")).write_text(source)
                flash = ((REFERENCE if language == "min" else out / "kernel") / "flash.bin").read_bytes()
                flash = insert(flash, "benchinit", address, hooks, fs)
                if language == "min":
                    flash = insert(flash, "bench.min", 0x8000, source.encode() + b"\0", fs)
                    uart = "benchinit\nmin bench.min\n"
                else:
                    uart = "benchinit\nminforth\n" + source
                (folder / "flash.bin").write_bytes(flash)
                for name, data in controls.items():
                    (folder / name).write_bytes(data)
                (folder / "uart.txt").write_text(uart)
                (folder / "profile.txt").write_text(configs[language])
                measurements = []
                for repeat in range(args.repeat):
                    ram_path = folder / f"ram-{repeat}.bin"
                    r = command([ROOT / "minredux/target/release/examples/benchmark", folder,
                                  folder / "uart.txt", ram_path, args.max_cycles,
                                  folder / "profile.txt"], timeout=args.host_timeout)
                    measurement = json.loads(r.stdout)
                    if "phases" not in measurement:
                        raise ValueError("observer did not return phase measurements")
                    ram = ram_path.read_bytes()
                    validate(case, language, measurement, ram)
                    if language == "min":
                        memory = measurement["memory"]
                        if memory["source_bytes"] != len(source.encode()) + 1:
                            raise ValueError("Min Loader source span disagrees with input")
                        if 0x8000 + memory["source_bytes"] + memory["token_bytes"] > 0xd000:
                            raise ValueError("Min source/tokens overlap benchmark workspace")
                    measurements.append(measurement)
                if len({m["raw_cycles"] for m in measurements}) != 1:
                    raise ValueError(f"{case.name}/{language}: nondeterministic execution cycles")
                if any(m != measurements[0] for m in measurements[1:]):
                    raise ValueError(f"{case.name}/{language}: nondeterministic phase/memory measurements")
                if args.verify_profile:
                    plain_ram = folder / "ram-unprofiled.bin"
                    plain = command([ROOT / "minredux/target/release/examples/benchmark", folder,
                                     folder / "uart.txt", plain_ram, args.max_cycles], timeout=args.host_timeout)
                    plain_measurement = json.loads(plain.stdout)
                    if any(measurements[0][key] != value for key, value in plain_measurement.items()):
                        raise ValueError("observer changed guest clocks/state")
                    if plain_ram.read_bytes() != (folder / "ram-0.bin").read_bytes():
                        raise ValueError("observer changed guest RAM")
                pair["languages"][language] = {
                    "source_bytes": len(source.encode()), "source_sha256": sha(source.encode()),
                    "flash_sha256": sha(flash), "measurements": measurements, "verified": True,
                    "observer_verified": args.verify_profile}
                save()
            mc = pair["languages"]["min"]["measurements"][0]["raw_cycles"]
            fc = pair["languages"]["forth"]["measurements"][0]["raw_cycles"]
            pair["raw_speedup"] = mc / fc
            print(f"PASS {case.name:12} Min={mc:12,} Forth={fc:12,} ratio={mc/fc:.3f}x", flush=True)
        report["status"] = "passed"
        if args.baseline:
            report["comparison"] = compare(json.loads(args.baseline.read_text()), report)
            for row in report["comparison"]:
                print(f"DIFF {row['case']:12} {row['language']:5} cycles {row['delta_percent']:+.3f}%", flush=True)
        save()
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if isinstance(error, subprocess.CalledProcessError):
            report["error_stdout"] = error.stdout
            report["error_stderr"] = error.stderr
        save()
        print(json.dumps(report.get("error_stderr", report["error"])), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
