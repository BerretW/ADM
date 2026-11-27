# Mission decisions

Record evidence, consequences, compatibility, and tests for each accepted
decision. Items below are pending investigation unless explicitly marked
confirmed.

## Confirmed constraints
- Work on the actual current checkout; never reset to the external audit
  baseline or discard newer changes.
- Preserve the previous mission history at `.ai/archive/1f5c763/`.
- Do not create a standalone ADM Editor. Extend the existing Blender and World
  Tile authoring applications.
- Keep frozen shader/profile identities and meanings unchanged. New behavior
  must be opt-in and versioned.
- Do not claim renderer support from metadata, reference math, or a skipped
  test. Verify rendered output where the request requires actual rendering.
- Treat the pasted attachment as a read-only source; `.ai/MISSION.md` is its
  working copy.

## Pending audit and design decisions
- Compare palette reduction, region assignment, boundary refinement, control
  maps, wider profiles and texture arrays against actual seam/render fixtures.
  Choose only after measuring representability, compatibility, cost and error.
- Determine the correct strict-export behavior and a user-visible definition of
  approximation before changing export defaults.
- Audit existing physical material/collider schemas before adding fields or
  registries; avoid duplicate friction/restitution semantics.
- Compare versioned BC5 fallback designs and prove primary-byte preservation,
  sampler/UV retention, core-PBR behavior and layered-shader compatibility.
- Derive parameter ranges, equations, sampling order, fallbacks and capabilities
  from explicit contracts and reference tests, not renderer assumptions.
- Verify VTK/Blender shader-hook behavior and budgets against actual supported
  runtimes before claiming combinations are supported.

## Evidence log
No new implementation or contract decisions are approved yet. Add references to
the exact source, fixture and test when decisions are resolved.
