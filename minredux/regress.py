#!/usr/bin/env python3
"""Small regression suite for the minforth kernel (headless)."""
import argparse, subprocess, sys

CASES = [
    ("colon",     [": test 1 2 + . ;", "test"], "3"),
    ("if-true",   [": t3 IF 111 . ELSE 222 . THEN ;", "1 t3"], "111"),
    ("if-false",  [": t3 IF 111 . ELSE 222 . THEN ;", "0 t3"], "222"),
    ("if-then-f", [": t IF 111 . THEN 222 . ;", "0 t"], "222"),
    ("if-nest-t", [": t DUP IF DUP IF 10 . ELSE 20 . THEN",
                   "ELSE 30 . THEN DROP ;", "1 t"], "10"),
    ("if-nest-f", [": t DUP IF DUP IF 10 . ELSE 20 . THEN",
                   "ELSE 30 . THEN DROP ;", "0 t"], "30"),
    ("if-loop",   [": t 5 0 DO I 2 = IF 99 . ELSE I . THEN LOOP ;", "t"],
                  "0 1 99 3 4"),
    ("begin",     [": t4 0 BEGIN 1+ DUP 5 = UNTIL . ;", "t4"], "5"),
    ("while",     [": t5 0 BEGIN DUP 5 < WHILE 1+ REPEAT . ;", "t5"], "5"),
    ("while-else",[": t 0 BEGIN DUP 4 < WHILE DUP 2 = IF 9 .",
                   "ELSE DUP . THEN 1+ REPEAT DROP ;", "t"], "0 1 9 3"),
    ("exit",      [": t6 1 EXIT 2 ;", "t6 ."], "1"),
    ("variable",  ["VARIABLE v", "42 v !", "v @ ."], "42"),
    ("constant",  ["7 CONSTANT seven", "seven ."], "7"),
    ("rstack",    [": t7 5 >R 6 R@ + R> + . ;", "t7"], "16"),
    ("do",        [": t 0 10 0 DO I + LOOP . ;", "t"], "45"),
    ("nested-j",  [": n 0 3 0 DO 3 0 DO I J + + LOOP LOOP . ;", "n"], "18"),
    ("leave",     [": q 10 0 DO I 5 = IF LEAVE THEN I . LOOP ;", "q"], "0 1 2 3 4"),
    ("unloop",    [": u 10 0 DO I 5 = IF UNLOOP EXIT THEN I . LOOP ;", "u"], "0 1 2 3 4"),
    ("rbalance",  [": c 5 >R ;", "c", "1 2 + ."], "3"),
    ("mem",       ["VARIABLE x", "99 x !", "x @ .", "88 x C!", "x C@ ."], "99 88"),
    ("store-sp",  ["VARIABLE x", "11 22 x ! . x @ ."], "11 22"),
    ("cstore-sp", ["VARIABLE x", "11 22 x C! . x C@ ."], "11 22"),
    ("addstore-sp", ["VARIABLE x", "11 22 x +! . x @ ."], "11 22"),
    ("dotq",      [': hi ." Hi!" CR ;', "hi", ': dots 3 0 DO ." ." LOOP CR ;', "dots"], "Hi!"),
    ("numbers",   ["255 . 65535 . 0 . 4660 . 12345 ."], "255 65535 0 4660 12345"),
    ("hex",       ["HEX DEAD . 255 . DECIMAL 255 ."], "DEAD 255 255"),
    ("nested-j2", [": nj 3 0 DO 2 0 DO J . LOOP LOOP ;", "nj"], "0 0 1 1 2 2"),
    ("nested-lv", [": nl 3 0 DO 5 0 DO I 2 = IF LEAVE THEN", "LOOP I . LOOP ;", "nl"], "0 1 2"),
    ("loop16",    [": s 0 300 0 DO I + LOOP . ;", "s"], "44850"),
    ("loopcross", [": w 260 250 DO I . LOOP ;", "w"], "250 251 252 253 254 255 256 257 258 259"),
    ("clean",     [": clean 3 . ;", "clean"], "3"),
    ("mul",       ["300 200 * ."], "60000"),
    ("mulwrap",   ["65535 65535 * ."], "1"),
    ("mul-sp",    ["11 6 7 * . ."], "42 11"),
    ("div-sp",    ["11 100 7 / . ."], "14 11"),
    ("mod-sp",    ["11 100 7 MOD . ."], "2 11"),
    ("sq",        [": sq DUP * ;", "12 sq ."], "144"),
    ("div",       ["1000 300 / . 1000 300 MOD ."], "3 100"),
    ("div16",     ["65535 65535 / . 65535 65535 MOD ."], "1 0"),
]

def screen(lines, cycles="6000000", rom_dir="../minforth/build"):
    data = "minforth\n" + "\n".join(lines) + "\n"
    h = data.encode().hex()
    cmd = ["./target/release/minredux", "run", "--rom-dir", rom_dir,
           "--cycles", cycles, "--no-output", "--uart-hex", h,
           "--uart-after", "200000", "--text"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return "\n".join(out.splitlines()[8:22])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom-dir", default="../minforth/build",
                        help="image directory containing the minforth program and control ROMs")
    args = parser.parse_args()
    ok = 0
    for name, lines, expect in CASES:
        text = screen(lines, rom_dir=args.rom_dir)
        # No case legitimately prints '?', so a '?' means an undefined word
        # was executed or a glyph failed to decode (e.g. the block cursor).
        good = expect in text and "?" not in text
        ok += good
        print(f"{'PASS' if good else 'FAIL'} {name:10} expected {expect!r}")
        if not good:
            print(text.replace(" ", "\u00b7"))
    print(f"\n{ok}/{len(CASES)} passed")
    return 0 if ok == len(CASES) else 1

if __name__ == "__main__":
    raise SystemExit(main())
