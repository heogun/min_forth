#!/usr/bin/env python3
"""End-to-end checks for the kernel's colour/SN76489 words on minredux-cs.

Runs runtime Forth through the release emulator and inspects the extension
state it dumps (--dump-ext), the decoded screen, the PPM frame and the WAV.
Rebuild the kernel image and `cargo build --release` first; this script does
neither.  Run from minredux-cs/.
"""
import argparse
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

EXE = "./target/release/minredux-cs"
VIEW_CELLS = [(row + 2) * 64 + col + 12 for row in range(30) for col in range(50)]


def run(lines, cycles=6_000_000, wav=False, ppm=False):
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        data = ("minforth\n" + "\n".join(lines) + "\n").encode().hex()
        cmd = [EXE, "run", "--rom-dir", "../minforth/build", "--cycles", str(cycles),
               "--no-output", "--uart-hex", data, "--uart-after", "200000", "--text",
               "--dump-ext", str(folder / "ext.json")]
        if wav:
            cmd += ["--wav", str(folder / "a.wav"), "--audio-rate", "48000"]
        if ppm:
            cmd += ["--ppm", str(folder / "f.ppm")]
        text = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        ext = json.loads((folder / "ext.json").read_text())
        ext["attr"] = bytes.fromhex(ext.pop("attributes"))
        ext["text"] = text
        if wav:
            ext["wav"] = (folder / "a.wav").read_bytes()
        if ppm:
            ext["ppm"] = (folder / "f.ppm").read_bytes()
        return ext


def last_output(text, marker):
    """Screen row printed after the input line `marker`."""
    rows = [r.rstrip() for r in text.splitlines()]
    for i in range(len(rows) - 1, -1, -1):
        if rows[i] == marker:
            return rows[i + 1].strip() if i + 1 < len(rows) else ""
    return None


def wav_frequency(blob):
    rate = struct.unpack_from("<I", blob, 24)[0]
    pcm = struct.unpack_from(f"<{(len(blob) - 44) // 2}h", blob, 44)
    first = next(i for i, s in enumerate(pcm) if s != 0)
    body = pcm[first:]
    mean = sum(body) / len(body)
    rises = [i for i in range(1, len(body)) if body[i - 1] <= mean < body[i]]
    if len(rises) < 3:
        return 0.0
    return rate * (len(rises) - 1) / (rises[-1] - rises[0])


def common(ext, check):
    check(ext["protocol_errors"] == 0, f"protocol_errors={ext['protocol_errors']}")
    check(ext["vreg_overwrites"] == 0, f"vreg_overwrites={ext['vreg_overwrites']}")
    check(ext["control"] & 0x06 == 0, f"strobe/attr bit left set: {ext['control']:#x}")


def case_attr_store(check):
    e = run(["HEX 1E 0 0 ATTR! 4F 31 1D ATTR! DECIMAL", "1 2 + ."])
    common(e, check)
    check(e["attr"][2 * 64 + 12] == 0x1E, "cell (0,0)")
    check(e["attr"][31 * 64 + 61] == 0x4F, "cell (49,29)")
    check(sum(1 for b in e["attr"] if b) == 2, "only two cells written")
    check(last_output(e["text"], "1 2 + .") == "3", "printing works after ATTR!")


def case_attr_range(check):
    e = run([": keep 7 . ;", "HEX 77 32 0 ATTR! 77 0 1E ATTR! 77 FF FF ATTR! DECIMAL",
             "keep"])
    common(e, check)
    check(not any(e["attr"]), "out-of-range cells ignored")
    check(last_output(e["text"], "keep") == "7", "dictionary intact")


def case_attr_fill(check):
    e = run(["HEX 1F ATTRFILL DECIMAL", "5 ."])
    common(e, check)
    view = set(VIEW_CELLS)
    check(all(e["attr"][i] == 0x1F for i in view), "every viewport cell")
    check(not any(b for i, b in enumerate(e["attr"]) if i not in view), "no border cells")
    check(last_output(e["text"], "5 .") == "5", "printing works after ATTRFILL")


def case_control(check):
    e = run(["1 COLOR 256 AUDIO 0 COLOR"])
    common(e, check)
    check(e["control"] == 0x08, f"control={e['control']:#x}")
    e = run(["1 AUDIO 1 COLOR 0 AUDIO"])
    check(e["control"] == 0x01, f"control={e['control']:#x}")


def case_sn_registers(check):
    e = run(["SILENCE", "254 1 TONE 5 1 VOL 6 NOISE 1023 0 TONE 3 2 TONE",
             "HEX 9F SN! DECIMAL"])
    common(e, check)
    r = e["sn_registers"]
    check(r[2] == 254 and r[3] == 5, f"ch1 tone/vol {r[2]}/{r[3]}")
    check(r[0] == 1023 and r[1] == 15, f"ch0 tone/vol {r[0]}/{r[1]}")
    check(r[4] == 3 and r[5] == 15, f"ch2 tone/vol {r[4]}/{r[5]}")
    check(r[6] == 6 and r[7] == 15, f"noise/vol {r[6]}/{r[7]}")


def case_tone_audio(check):
    e = run(["SILENCE 254 0 TONE 0 0 VOL 1 AUDIO"], cycles=9_000_000, wav=True)
    common(e, check)
    expected = 3_579_545 / (32 * 254)
    freq = wav_frequency(e["wav"])
    check(abs(freq - expected) / expected < 0.01, f"tone {freq:.1f} Hz, want {expected:.1f}")


def case_colour_frame(check):
    e = run(["HEX 1E ATTRFILL DECIMAL 1 COLOR"], ppm=True)
    common(e, check)
    ppm = e["ppm"]
    header = b"P6\n400 240\n255\n"
    check(ppm.startswith(header), "ppm header")
    pixels = {ppm[i:i + 3] for i in range(len(header), len(ppm), 3)}
    # 0x1E: background 1 = blue (2/3 level); foreground E = I+R+G, and the
    # intensity bit lifts blue to 1/3 as well: level = (2*C + I) / 3.
    check(pixels == {bytes([0, 0, 170]), bytes([255, 255, 85])}, f"palette {pixels}")


CASES = [case_attr_store, case_attr_range, case_attr_fill, case_control,
         case_sn_registers, case_tone_audio, case_colour_frame]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    passed = 0
    for case in CASES:
        failures = []

        def check(cond, msg):
            if not cond:
                failures.append(msg)

        try:
            case(check)
        except Exception as exc:  # report and continue with the next case
            failures.append(f"exception: {exc!r}")
        name = case.__name__[5:]
        if failures:
            print(f"FAIL {name}: " + "; ".join(failures))
        else:
            passed += 1
            if args.verbose:
                print(f"ok   {name}")
    print(f"\n{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
