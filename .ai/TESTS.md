# Mission verification record

Record exact commands, environment, outcomes, skips and artifact paths. A skip
is not evidence that a requirement passed.

## Baseline and environment
- Intake checkout: Windows, `main`, `1f5c7638bd014bbe7d24e347d5600fdcdedffe46`.
- The prior `.ai/FINAL_REPORT.md` records historical checks for Blender 5.2.3
  and World Tile with VTK 9.7.2; those checks precede this mission and do not
  establish current mission conformance.
- Baseline dependencies and current test commands: **pending verification**.
- Baseline full/check-only build: **pending verification**.

## New mission runs
No tests have been run for this mission yet.

| Date | Command / artifact | Environment | Result | Notes |
|---|---|---|---|---|
| | | | | |

## Required evidence before closeout
- Normative contract fixtures and deterministic reference math.
- Palette conflict, strict/approximate export, pixel/seam, slot permutation,
  mixed LOD and irregular/curved terrain render tests.
- Control/Macro Map, anti-tiling, triplanar, detail, self-shadowing and
  displacement vectors including edge cases and bounded resource use.
- Physical registry, collider assignment/query, independent collision,
  boundary refinement and round-trip tests.
- BC5 fallback/source-byte preservation plus R16, mipmap and embedded/external
  GPU texture cases.
- World Tile old/new persistence, GUI binding, generation, selective
  invalidation, portability and atomic export.
- Blender runtime registration, node/render tests, import/export, save/reload,
  collider and texture cases.
- Consumer support audit and actual rendered artifacts.
- Package integrity and isolated installation checks.
