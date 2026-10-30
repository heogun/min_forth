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
