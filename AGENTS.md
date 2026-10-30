# Workspace guide

## Boundaries

- `minredux/` is the dependency-free Rust (edition 2024) cycle-exact **Revision 1.4 Redux** emulator: `src/lib.rs` models hardware; `src/main.rs` supplies headless, benchmark, and terminal frontends. Corrected ROMs are installed IN PLACE at `minimal64/Revision 1.4 Redux/FLASH Images/`; this path no longer means original ROMs. The user retired/deleted old ROMs on 2026-10-30. Do not require/recreate a separate `roms/` bundle or restore old ROMs. Verify the corrected installed images with `python3 minredux/verify_rom.py`.
- `minforth/forth/kernel.fs` is assembly with a custom preprocessor, **not host Forth**. `minforth/test/` mixes assembly test programs with runtime Forth (`speed.fs`); inspect the contents before choosing a runner.
- `minimal64/Revision 1.4 Redux/` supplies the reference ROMs, microcode CSVs, MinOS sources, and assembler. `PROGRESS.md` records implementation history and debugging lessons; prefer current scripts over its recorded sizes/counts.
- `extended-min/` is a separate interpreter/toolchain. Read `extended-min/AGENTS.md` and `extended-min/ARCHITECTURE.md` before editing it; use its local skills where applicable. It uses global BespokeASM, not the bundled slu4 assembler used by Forth. Keep its two targets synchronized and compile default + `USE_ACCELERATOR` for each, as its guide requires.

## Build and verify Forth/emulator

Run the kernel build from the workspace root:

```sh
python3 minforth/tools/build.py minforth/forth/kernel.fs minforth 0x1000
```

- This requires the native executable `minforth/tools/asm`. To rebuild it from the bundled source: `clang++ -O2 -std=c++11 minforth/tools/asm.cpp -o minforth/tools/asm`.
- `build.py` prepends `forth/defs.inc`, preprocesses macros/includes, requires an explicit `#org` matching the destination argument, and inserts the result into the MinOS flash filesystem.
- Default output is `minforth/build/`. Its `flash.bin` is patched **in place** across builds; only the first build copies the installed MinOS flash. Corrected control ROMs are copied from the primary path on every build. The builder verifies pinned ROM hashes/CSV first and exports `<name>.symbols.json`. Use `--out DIR` for isolated program images.

Then run from `minredux/` (the Python helpers hardcode cwd-relative executable and ROM paths):

```sh
cargo build --release
python3 regress.py
python3 runline.py ': t 0 10 0 DO I + LOOP . ;' 't'
python3 runfs.py ../minforth/test/speed.fs --cycles 40000000 --no-output --until-text END
```

- Rebuild the kernel image after assembly edits and the release executable after Rust edits **before** running these helpers; they do neither automatically. `regress.py` is the end-to-end kernel suite, not `cargo test`.
- `runline.py` is the focused check for one or more runtime Forth input lines. `runfs.py` strips backslash comments and reflows whitespace-separated tokens to 46 columns; it is not a syntax-aware string-preserving loader.
- For interactive use from `minredux/`: `./target/release/minredux term --rom-dir ../minforth/build`; exit with **Ctrl-]**. The CLI's default ROM directory boots corrected control ROMs with unchanged MinOS program FLASH, not the Forth kernel.
- Rust validation uses only the corrected installed images: `cargo test --all-targets` includes the observer unit tests, or `cargo test fixed_rom` runs focused checks. Historical defective behavior is documentation, not an accepted exception in the active semantic oracle; no deleted old-ROM copy is needed.
- Direct headless UART input should start with `minforth\n` and use `--uart-after 200000` to wait for MinOS boot. Use `--text` for decoded screen output; `--until-text` can miss a marker split across the 50-column screen boundary.

## Kernel invariants

- Subroutine-threaded bodies use `JPS`/`RTS`; the kernel loads at `0x1000`, the split-byte data stack occupies `0x3000/0x3100`, loop frames start at `0x2800`, and the dictionary grows from `0x8000`. Check `forth/defs.inc` for named zero-page state and MinOS entrypoints before allocating scratch space.
- `JPS` clobbers A; use `JAS` when passing A to helpers such as `nf_cbyte`. `nf_cbyte` also clobbers `zPTR`; preserve live pointers elsewhere.
- Keep the tokenizer cursor in private `zIVEC`: MinOS printing helpers clobber `_ReadPtr`.
- The active loop's index/limit are cached in `zCIDX`/`zCLIM`; inner `DO` must flush the outer index to its frame for `J`, and `nf_lpop` must restore the outer cache.
- `nfDefHere`/`nfDefLatest` reserve `0x26c0..0x26c3` for pre-colon rollback checkpoints; keep kernel code below this range. `ABORT"` abandons all return frames, clears stack/loop/compiler depths, rolls back any active colon definition, and resumes at `wRepl` without resetting BASE or completed dictionary entries.
