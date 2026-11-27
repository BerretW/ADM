# Technical debt

This file tracks issues confirmed during the current mission. Verify each
starting observation before treating it as current debt. Every entry must state
severity, cause, workaround, proposed fix, and source/test evidence.

## Starting observations to verify

### Four-layer palette conflicts
- **Severity:** High; different per-triangle palettes can create visible seams
  when more than four surfaces have nonzero weights.
- **Cause:** A four-layer primitive cannot represent arbitrary five-plus
  simultaneous weights; prior export trimmed per-triangle palettes.
- **Workaround:** None accepted as final. Do not suppress the existing conflict
  diagnostic or describe lossy output as seam-free.
- **Next step:** Reproduce and compare deterministic reduction, regional
  assignment, boundary refinement, Control Maps and wider profiles with
  rendered seam tests.
- **Evidence:** Previous mission `.ai/TECHNICAL_DEBT.md` (archived).

### Blender standalone core-PBR BC5 fallback
- **Severity:** High for portable normal-map use.
- **Cause:** The primary BC5 data and current RGB fallback contract have
  incompatible channel requirements in the standalone path.
- **Workaround:** No general workaround is accepted until verified against the
  exact current exporter and reader behavior.
- **Next step:** Design and test a versioned, unambiguous representation that
  retains original BC5 bytes.
- **Evidence:** Previous mission `.ai/TECHNICAL_DEBT.md` (archived).

### Preview and renderer limitations
- **Severity:** Medium; CPU composition and missing Blender POM rendering are
  not equivalent to shader execution.
- **Cause:** Existing renderer paths differ in sampling and effect support.
- **Workaround:** Clearly label approximations and rely only on tested actual
  shader previews for effects they implement.
- **Next step:** Extend existing renderers where feasible; verify pixels and
  report remaining backend limits.
- **Evidence:** Previous mission closeout and World Tile tests (archived).

### Opaque extension references
- **Severity:** High when editing/re-exporting data with unknown references.
- **Cause:** Unknown schemas do not identify which values reference ADM objects.
- **Workaround:** Preserve opaque JSON only where supported and reject unsafe
  transformations; never guess references from numeric values.
- **Next step:** Add explicit reference declarations only if justified by
  current formats and tested consumers.
- **Evidence:** Previous mission `.ai/TECHNICAL_DEBT.md` (archived).

### Multiplatform codecs and Blender cycle diagnostics
- **Severity:** Medium to high depending on release target.
- **Cause:** Historical verification was Windows-focused; Blender dependency
  cycles were observed without a confirmed minimal reproducer.
- **Workaround:** State the tested platform/runtime and preserve diagnostics.
- **Next step:** Test supported platforms where available; isolate cycle sources
  before attempting targeted fixes.
- **Evidence:** Previous mission closeout and test records (archived).
