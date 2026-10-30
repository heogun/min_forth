"""Paired 16-bit algorithms and independent, unbounded-integer references.

Sources are generated verbatim into each run directory for review and hashing.
No guest algorithm calls native/assembly helpers other than timing RTS hooks.
"""
from dataclasses import dataclass
import struct


@dataclass
class Case:
    name: str
    stage: int
    parameters: dict
    min_setup: str
    min_body: str
    forth_setup: str
    forth_body: str
    expected: bytes
    address: int = 0xe000


def cells(values):
    return b"".join(struct.pack("<H", x & 0xffff) for x in values)


def basic_cases():
    yield Case("empty", 1, {}, "", "", "", "", b"")
    n = 1024
    primes = bytes(int(i >= 2 and all(i % d for d in range(2, int(i**0.5) + 1)))
                   for i in range(n))
    yield Case("sieve", 1, {"limit_exclusive": n},
        "char a @ 0xe000\nint i=0\nint j=0",
        f"""i=0
while i<{n}:
  a[i]=1
  i+=1
a[0]=0; a[1]=0
i=2
while i*i<{n}:
  if a[i]!=0:
    j=i*i
    while j<{n}:
      a[j]=0
      j=j+i
  i+=1""",
        "VARIABLE p VARIABLE q",
        f"""{n} 0 DO 1 57344 I + C! LOOP
0 57344 C! 0 57345 C!
2 p !
BEGIN p @ p @ * {n} < WHILE
  57344 p @ + C@ IF
    p @ p @ * q !
    BEGIN q @ {n} < WHILE
      0 57344 q @ + C!
      p @ q +!
    REPEAT
  THEN
  1 p +!
REPEAT""", primes)
    n = 32
    values = [(i * 109 + 37) % 251 for i in range(n)]
    yield Case("bubble", 1, {"elements": n, "input": "(i*109+37)%251"},
        f"""int a @ 0xe000
int i=0
int j=0
int t=0
while i<{n}:
  a[i]=(i*109+37)-(i*109+37)/251*251
  i+=1""",
        f"""i=0
while i<{n-1}:
  j=0
  while j<{n-1}-i:
    if a[j]>a[j+1]:
      t=a[j]; a[j]=a[j+1]; a[j+1]=t
    j+=1
  i+=1""",
        f"VARIABLE x VARIABLE y VARIABLE t\n: init {n} 0 DO I 109 * 37 + 251 MOD 57344 I 2* + ! LOOP ;\ninit",
        f"""{n-1} 0 DO
  {n-1} I - 0 DO
    57344 I 2* + x ! x @ 2 + y !
    x @ @ y @ @ > IF
      x @ @ t ! y @ @ x @ ! t @ y @ !
    THEN
  LOOP
LOOP""", cells(sorted(values)))
    n = 4
    a = [(i * 3 + 1) % 8 for i in range(n*n)]
    b = [(i * 5 + 2) % 8 for i in range(n*n)]
    c = [sum(a[i*n+k] * b[k*n+j] for k in range(n))
         for i in range(n) for j in range(n)]
    yield Case("matrix", 1, {"dimension": n},
        f"""int a @ 0xd000
int b @ 0xd100
int c @ 0xe000
int i=0
int j=0
int k=0
int s=0
while i<{n*n}:
  a[i]=(i*3+1) and 7; b[i]=(i*5+2) and 7
  i+=1""",
        f"""i=0
while i<{n}:
  j=0
  while j<{n}:
    s=0; k=0
    while k<{n}:
      s=s+a[i*{n}+k]*b[k*{n}+j]
      k+=1
    c[i*{n}+j]=s
    j+=1
  i+=1""",
        f"""VARIABLE row VARIABLE col VARIABLE k VARIABLE s
: init {n*n} 0 DO
  I 3 * 1+ 8 MOD 53248 I 2* + !
  I 5 * 2 + 8 MOD 53504 I 2* + !
LOOP ; init""",
        f"""{n} 0 DO I row !
  {n} 0 DO I col ! 0 s !
    {n} 0 DO I k !
      53248 row @ {n} * k @ + 2* + @
      53504 k @ {n} * col @ + 2* + @ * s +!
    LOOP
    s @ 57344 row @ {n} * col @ + 2* + !
  LOOP
LOOP""", cells(c))
    # Min's interpreter and recursive expressions share a 256-byte hardware
    # stack. Keep the common task shallow; larger depths must be validated.
    n = 6
    x, y = 0, 1
    for _ in range(n):
        x, y = y, x+y
    yield Case("fib", 1, {"n": n, "algorithm": "naive recursive"},
        """def fib(int n):
  if n<2: return n
  return fib(n-1)+fib(n-2)
int result @ 0xe000""",
        f"result=fib({n})",
        ": fib DUP 2 < IF EXIT THEN DUP 1- fib SWAP 2 - fib + ;",
        f"{n} fib 57344 !", cells([x]))


def crc16(data):
    """CRC-16/MODBUS: reflected 0xa001, init ffff, xorout 0."""
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def extended_cases():
    n = 128
    data = bytes((i * 17 + 3) & 255 for i in range(n))
    yield Case("crc16", 2, {"bytes": n, "variant": "CRC-16/MODBUS", "seed": "(i*17+3)&255"},
        f"""char data @ 0xd000
int result @ 0xe000
int i=0
int j=0
int crc=0xffff
while i<{n}:
  data[i]=(i*17+3) and 255
  i+=1""",
        f"""i=0
while i<{n}:
  crc=crc xor (data[i] and 255)
  j=0
  while j<8:
    if (crc and 1)!=0: crc=(crc>>1) xor 0xa001
    else: crc=crc>>1
    j+=1
  i+=1
result=crc""",
        f"""VARIABLE crc
: init {n} 0 DO I 17 * 3 + 255 AND 53248 I + C! LOOP ; init
: ur1 2/ 32767 AND ;""",
        f"""65535 crc !
{n} 0 DO
  crc @ 53248 I + C@ XOR crc !
  8 0 DO
    crc @ 1 AND IF crc @ ur1 40961 XOR
    ELSE crc @ ur1 THEN crc !
  LOOP
LOOP
crc @ 57344 !""", cells([crc16(data)]))
    # Count all overlapping occurrences; include successes, late failures and
    # a match at the last possible position. No language string library calls.
    data = (b"ABABACABABAQ" * 11)[:128]
    data = data[:-5] + b"ABABA"
    pattern = b"ABABA"
    n, m = len(data), len(pattern)
    expected = sum(data[i:i+m] == pattern for i in range(n-m+1))
    min_init = "\n".join(f"data[{i}]={b}" for i, b in enumerate(data))
    min_init += "\n" + "\n".join(f"pat[{i}]={b}" for i, b in enumerate(pattern))
    forth_init = " ".join(f"{b} {53248+i} C!" for i, b in enumerate(data))
    forth_init += " " + " ".join(f"{b} {53504+i} C!" for i, b in enumerate(pattern))
    yield Case("search", 2, {"bytes": n, "pattern_hex": pattern.hex(), "overlapping": True},
        "char data @ 0xd000\nchar pat @ 0xd100\nint result @ 0xe000\nint i=0\nint j=0\nint count=0\n" + min_init,
        f"""i=0
while i<{n-m+1}:
  j=0
  while j<{m}:
    if data[i+j]!=pat[j]: break
    j+=1
  if j=={m}: count+=1
  i+=1
result=count""",
        "VARIABLE pos VARIABLE j VARIABLE count\n: init " + forth_init + " ; init",
        f"""0 count !
{n-m+1} 0 DO
  I pos ! 0 j !
  BEGIN j @ {m} < WHILE
    53248 pos @ + j @ + C@ 53504 j @ + C@ = IF
      1 j +!
    ELSE
      {m+1} j !
    THEN
  REPEAT
  j @ {m} = IF 1 count +! THEN
LOOP
count @ 57344 !""", cells([expected]))


def trunc32(value):
    """Signed divide by 32, truncate toward zero (no floating point)."""
    return -(abs(value) // 32) if value < 0 else value // 32


def mandelbrot_reference(width=16, height=12, step=6, iterations=24):
    result = []
    for row in range(height):
        for col in range(width):
            cx, cy = -64 + step * col, -36 + step * row
            x = y = count = 0
            while count < iterations:
                # The guard avoids signed-16 square overflow after a point has
                # escaped. For guarded inputs squares and 2*x*y fit in s16.
                if abs(x) > 64 or abs(y) > 64 or x*x + y*y > 4096:
                    break
                xx, yy, xy2 = x*x, y*y, 2*x*y
                assert max(abs(xx-yy), abs(xy2), xx+yy) <= 32767
                x, y = trunc32(xx-yy) + cx, trunc32(xy2) + cy
                count += 1
            result.append(count)
    return bytes(result)


def mandelbrot_cases():
    w, h, step, limit = 16, 12, 6, 24
    yield Case("mandelbrot", 3,
        {"width": w, "height": h, "coordinate_step": step,
         "cx_start": -64, "cy_start": -36, "scale": 32,
         "max_iterations": limit, "rounding": "truncate toward zero",
         "escape": "x*x+y*y>4096, before update; z0=0"},
        """char output @ 0xe000
int row=0
int col=0
int cx=0
int cy=0
int x=0
int y=0
int xx=0
int yy=0
int nx=0
int k=0""",
        f"""row=0
while row<{h}:
  cy=-36+row*{step}
  col=0
  while col<{w}:
    cx=-64+col*{step}
    x=0; y=0; k=0
    while k<{limit}:
      if x < -64 or x > 64 or y < -64 or y > 64: break
      xx=x*x; yy=y*y
      if xx+yy>4096: break
      nx=(xx-yy)/32+cx
      y=(2*x*y)/32+cy
      x=nx
      k+=1
    output[row*{w}+col]=k
    col+=1
  row+=1""",
        f"""VARIABLE row VARIABLE col VARIABLE cx VARIABLE cy
VARIABLE zx VARIABLE zy VARIABLE xx VARIABLE yy VARIABLE nx
: abs DUP 32768 AND IF NEGATE THEN ;
: sd32 DUP 32768 AND IF NEGATE 32 / NEGATE ELSE 32 / THEN ;
: pixel 0 zx ! 0 zy !
  {limit} 0 DO
    zx @ abs 64 > zy @ abs 64 > OR IF I UNLOOP EXIT THEN
    zx @ zx @ * xx ! zy @ zy @ * yy !
    xx @ yy @ + 4096 > IF I UNLOOP EXIT THEN
    xx @ yy @ - sd32 cx @ + nx !
    2 zx @ * zy @ * sd32 cy @ + zy ! nx @ zx !
  LOOP {limit} ;""",
        f"""{h} 0 DO I row ! I {step} * 36 - cy !
  {w} 0 DO I col ! I {step} * 64 - cx !
    pixel 57344 row @ {w} * col @ + + C!
  LOOP
LOOP""", mandelbrot_reference(w, h, step, limit))


def diagnostic_cases():
    """Small paired workloads, NOT additional overall-language score items."""
    n = 64
    yield Case("micro-call", 0, {"iterations": n, "kind": "diagnostic"},
        "def inc1(int n): return n+1\nint i=0\nint s=0\nint result @ 0xe000",
        f"while i<{n}:\n  s=s+inc1(i)\n  i+=1\nresult=s",
        ": inc1 1+ ;", f"0 {n} 0 DO I inc1 + LOOP 57344 !", cells([n*(n+1)//2]))
    yield Case("micro-stack", 0, {"iterations": n, "kind": "diagnostic"},
        "int i=0\nint s=0\nint result @ 0xe000",
        f"while i<{n}:\n  s=s+i+3\n  i+=1\nresult=s",
        "", f"0 {n} 0 DO I 3 OVER + SWAP DROP + LOOP 57344 !", cells([n*(n-1)//2+3*n]))
    yield Case("micro-do", 0, {"entries": n, "inner_iterations": 3, "kind": "diagnostic"},
        "int i=0\nint j=0\nint s=0\nint result @ 0xe000",
        f"while i<{n}:\n  j=0\n  while j<3:\n    s=s+j\n    j+=1\n  i+=1\nresult=s",
        "", f"0 {n} 0 DO 3 0 DO I + LOOP LOOP 57344 !", cells([3*n]))
    count = 32
    yield Case("micro-parse", 0, {"numbers": count, "digits": 4, "kind": "diagnostic"},
        "def literals():\n  int x=0\n" + "  x=1234\n"*count
        + "  return 0\nint result @ 0xe000",
        "result=literals()",
        ": literals " + "1234 DROP "*count + ";", "literals 0 57344 !", cells([0]))


def sources(case):
    min_source = (case.min_setup + "\ncall 0xdf00\n" + case.min_body
                  + "\ncall 0xdf10\n")
    # All generated tokens are ASCII, contain no quoted strings/comments and fit
    # the line editor. Do not use this reflow as a general Forth source loader.
    forth = case.forth_setup + "\n: bench 57088 EXECUTE\n" + case.forth_body
    forth += "\n57104 EXECUTE ;\nbench\n"
    lines, line = [], ""
    tokens = iter(forth.split())
    for token in tokens:
        # These words read a name from the CURRENT UART line. Unlike colon
        # bodies, their name cannot be continued on the next line.
        if token.upper() in ("VARIABLE", "CONSTANT", ":"):
            token += " " + next(tokens)
        if len(token) > 46:
            raise ValueError("generated token exceeds UART line limit")
        if line and len(line) + len(token) + 1 > 46:
            lines.append(line)
            line = ""
        line = (line + " " + token).strip()
    if line:
        lines.append(line)
    return min_source, "\n".join(lines) + "\n"
