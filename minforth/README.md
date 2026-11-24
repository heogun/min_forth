# Minforth kernel notes

`forth/kernel.fs` is assembly with the project's preprocessor, **not host
Forth**. Runtime Forth is sent to the kernel after MinOS launches `minforth`.

## `ABORT"` (compilation-only)

```forth
: require-nonzero 0= ABORT" zero rejected" ;
0 require-nonzero
1 2 + .
```

The example prints `zero rejected`, returns to the interpreter, and the next
input line prints `3`. This feature does not change the kernel's existing
comparison/division semantics.

Runtime stack effect is `( flag -- )`:

- Zero consumes only the flag, skips the inline counted string, and continues
  the current word. Other stack values survive.
- Any nonzero 16-bit value prints the message and a newline, abandons all
  callers, discards the rest of the current input line and returns to REPL.
- Data SP and hardware return SP become `fe`; the loop stack becomes empty at
  `2800`. Loop cache, compiler/control-stack depths and pending LEAVE count
  are cleared. Old storage is not zero-filled but becomes unreachable.
- BASE, completed dictionary definitions and variable contents survive.
- If an immediate word aborts while another definition is compiling, HERE
  and LATEST roll back to the checkpoint taken before that colon header.
- Direct interpretation use or a missing closing quote is rejected with a
  diagnostic and the same recovery/rollback, not partial inline code.

The message is raw ASCII up to the closing quote on the **same input line**.
One separating space is skipped. Spaces/case are preserved, empty strings
are supported, and there is no escape syntax or multiline-string extension.
Keep UART input lines within the existing editor limit (46 columns in helpers).
This is not a general CATCH/THROW implementation; no catchable exception code
or public standalone ABORT word is introduced.

The compiler checkpoint reserves RAM `26c0..26c3` (`nfDefHere`,
`nfDefLatest` in `forth/defs.inc`). Kernel code must end below it. Compiled
`ABORT"` uses `JPS wABORTQRT / length-byte / message`, like the existing `."`
layout; its false path repairs the caller return address across page boundaries.

## Colour + SN76489 extension words

For the CS-DRAFT-1 board (`hardware/redux-color-sound/`, emulated by
`minredux-cs/`). Registers live at `0xFEE0..0xFEEF`; see
`hardware/redux-color-sound/CIRCUIT.md`.

| Word | Stack | Effect |
| --- | --- | --- |
| `COLOR` | `( flag -- )` | colour output on/off (control bit 0) |
| `AUDIO` | `( flag -- )` | unmute/mute line-out (bit 3); send `SILENCE` first |
| `ATTR!` | `( attr col row -- )` | colour of one 8x8 cell, col 0..49, row 0..29 |
| `ATTRFILL` | `( attr -- )` | colour of all 50x30 cells |
| `SN!` | `( byte -- )` | one raw SN76489 command byte |
| `TONE` | `( period ch -- )` | tone ch 0..2, 10-bit period, f = 3579545/(32*N) |
| `VOL` | `( atten ch -- )` | ch 0..3 (3 = noise), 0 loudest .. 15 off |
| `NOISE` | `( mode -- )` | noise control, bit 2 white, bits 0..1 rate |
| `SILENCE` | `( -- )` | attenuation 15 on all four channels |

`attr` is `background<<4 | foreground`, each nibble `I:R:G:B`.
`ATTR!` writes through `0x440c + row*512 + col` (the cell's line 4): the board's
CPU write path takes the attribute row straight from A13..A9 with no +4 adder.

```forth
HEX 1E ATTRFILL 4F 0 0 ATTR! DECIMAL 1 COLOR
SILENCE 254 0 TONE 0 0 VOL 1 AUDIO     \ about 440 Hz on channel 0
```

- Flags are whole cells: any nonzero 16-bit value enables.
- Control is write-only. `zXCTL` (ZP `0x9e`) shadows bits 0 and 3 and is
  cleared at boot to match the RESET state; the words never read hardware back.
- Bits 1 (SN strobe) and 2 (attribute plane) are set only inside a word and
  are cleared before it returns, because attribute mode inhibits CPU reads of
  the `0x4000` bitmap mirror that MinOS printing relies on.
- `ATTR!` ignores rows >= 30 or columns >= 50 (low byte only), so no write
  can leave the bitmap window and hit the dictionary. Attributes do not scroll
  with text: MinOS scrolling moves only bitmap bytes.
- SN transfers follow the circuit's order: wait for READY, hold data, assert
  CE/WE, wait for READY high **while asserted**, release. Each READY wait
  gives up after 256 polls, so these words cannot hang on a board without the
  extension. There, the window is plain RAM and the writes are harmless,
  but nothing is played.
- The kernel does not touch the extension at boot. Run `SILENCE` before
  `1 AUDIO`, because the SN76489 has no reset input.
- These words sit at the oldest end of the primitive table, so the common
  newest-first `FIND` lookups do not scan them first.

From `minredux-cs/` after rebuilding the kernel and release binary:
`python3 ext_regress.py -v` (7 end-to-end cases: attribute cells and range
guard, fill, control shadow, SN registers, a 440 Hz tone measured from the WAV,
and the PPM palette, each also requiring zero SN protocol errors and zero VREG
overwrites).

## Build and test isolated images

From the workspace root:

```sh
python3 minforth/tools/build.py minforth/forth/kernel.fs minforth 0x1000 --out minforth/build-p1
```

The kernel builder also writes `minforth.symbols.json`, obtained from the same
preprocessed source and assembler as `minforth.bin`. The control ROMs it pairs
with are copied from **`minimal64/Revision 1.4 Redux/FLASH Images/`**, where the
corrected images are installed in place. Old ROMs and a separate `roms/` bundle
are not required. `python3 minredux/verify_rom.py` checks corrected hashes/CSV
before builds. The kernel must end below its checkpoint RAM at `26c0`.

From `minredux/`, rebuild the release frontend if needed, then:

```sh
cargo build --release
python3 regress.py --rom-dir ../minforth/build-p1
python3 abort_regress.py --rom-dir ../minforth/build-p1 -v
```

The dedicated 13-case ABORT suite checks whole-cell truth, false continuation,
message printing (not just input echo), same-line discard, nested callers and
return/loop stacks, incomplete-definition rollback including DO/LEAVE patches,
BASE/dictionary/variable preservation, repeated aborts and a page-crossing
inline string. See `../benchmark.md` for the P1 measurement harness.

## P2 compiler and stack optimizations

- A final compiled `JPS` becomes `JPA` only if no literal, string, branch or
  other byte followed it. Forward branches to the definition end retain an
  `RTS` at that target. `EXECUTE`, `>R`, `R>` and `R@` keep their call frames.
- `DROP`, `I`, `+`, `1+` and `C@` are inlined by primitive **xt**, not by name.
  Redefinitions and interpreted execution still use normal dictionary lookup.
  Templates must be position-independent and must not inspect return frames.
  `@`/`!` contain absolute INCW branches and cannot simply be copied this way.
- Binary arithmetic/comparisons and stores now consume stack cells by moving
  `zSP` directly, avoiding NP setup/copy. The split-byte layout and 8-bit SP
  behavior are unchanged; this does not add overflow/underflow checking.
- `zLastCall` (`9a..9b`), `zTailOK` (`9c`) and `zEndTarget` (`9d`) are private
  compiler state. Every byte emitter must invalidate the last two; currently
  all emitted definition bytes go through `nf_cbyte`.

The kernel is 4,988 bytes, ending at `237c`, below checkpoint RAM `26c0`.
Inlining saves execution clocks at a cost in dictionary size and compilation
time; measured before/after figures are in `../benchmark.md`.

For the current default image, rebuild from the workspace root without
`--out`, then from `minredux/` run:

```sh
python3 regress.py
python3 abort_regress.py
python3 p2_regress.py
```

The P2 suite checks generated instructions, retained branch/return targets,
inline byte equivalence and RAM results (including carry/borrow and memory
page crossing), rather than accepting echoed UART input as output. It uses
`../minforth/build` and its matching symbols.
