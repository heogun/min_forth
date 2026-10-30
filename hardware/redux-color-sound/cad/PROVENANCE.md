# Corrected Redux CAD baseline — not yet the color/sound board

Original work: **Carsten Herting (slu4), Minimal 64x4 Home Computer, Revision 1.4 Redux**.

- Upstream: <https://github.com/slu4coder/Minimal-64x4-Home-Computer>
- Source commit: `1a59c95695d1a6a6147584465ee87803fe9387da`
- Source directory: `Revision 1.4 Redux/KiCAD9/`
- Original license notice: **CC BY-NC-SA 4.0**.
- License: <https://creativecommons.org/licenses/by-nc-sa/4.0/>
- Legal code: <https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode>

This derivative baseline retains that attribution/license and the original schematic/PCB
license notices. It is supplied as-is, without warranty. It is not an upstream release or
an endorsement by the original author. This is a **noncommercial, share-alike CAD derivative**;
do not assume a permissive software license elsewhere in the workspace applies to these CAD files.
Embedded KiCad library definitions retain their upstream provenance and applicable library terms.

Changes made in this workspace on 2026-10-30:

1. Exported all 38 actual embedded schematic definitions to `Redux.kicad_sym` and referenced
   them explicitly. Pin numbers, types, positions and circuit connections are unchanged.
   This resolves stale cache/library comparisons without updating the electrical design.
2. Exported the existing J1/J3/J5 socket and RN1 footprint variants to
   `Redux_Footprints.pretty`; no socket/pad dimensions, positions, or copper were replaced.
3. Synchronized PCB Description/Datasheet fields with the schematic (90 field differences).
4. Renamed PCB `/Control Logic/~{VGA_TRY}` to `/Control Logic/~{VGA_WIN}`. Its two pads
   remain U7.3 and U1.9; the existing routed connections are unchanged.
5. Marked the decorative logo as board-only, excluded from BOM/position outputs, and
   synchronized its local library definition. It is not a missing electrical component.
6. Replaced platform-dependent TTF text with built-in KiCad stroke text, discarded stale
   render caches, enlarged/reflowed the feature legend and moved `READY.` to avoid silkscreen overlap.
7. Removed every original DRC exclusion. No rule was downgraded or newly ignored.
   Original project-wide ignored rule categories remain unchanged (see parent documentation).
8. Added project-relative library tables and source/invariant fingerprints.

Validation with KiCad **10.0.7**: ERC 0, DRC 0, schematic parity 0, unconnected 0,
excluded findings 0, including a DRC run with zones refilled in memory.
These results use the inherited project rule configuration, not every possible KiCad rule.
The source files remain unchanged. `baseline-invariants.json` records their hashes and
the normalized PCB copper/pad geometry fingerprint.

Open **`8-Bit CPU 32k.kicad_pro`** in this directory, not the upstream checkout.
This is a corrected **monochrome Redux baseline** for the subsequent integrated design.
Attribute color and SN76489 circuits have **not** been added. No manufacturing Gerbers are included.
