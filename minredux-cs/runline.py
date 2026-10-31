#!/usr/bin/env python3
import subprocess, sys

lines = sys.argv[1:]
data = "minforth\n" + "\n".join(lines) + "\n"
h = data.encode().hex()
cmd = [
    "./target/release/minredux-cs", "run",
    "--rom-dir", "../minforth/build",
    "--cycles", "6000000",
    "--no-output", "--uart-hex", h,
    "--uart-after", "200000", "--text",
]
out = subprocess.run(cmd, capture_output=True, text=True).stdout
rows = out.splitlines()[8:22]
for r in rows:
    print(r.replace(" ", "\u00b7") + "\u00b6")
