# `ADM_animation_timing_v1`

This normative ADM 1.0 extension preserves an authoring timeline's frame rate and per-clip frame
range alongside the core animation duration in seconds. Its schema version is `1.0.0`; its
capability is `ADM-ANIMATION-TIMING-1`. It does not change animation sample times, interpolation,
or playback semantics.

## Declaration and data

The top-level `.adm_anim` manifest declares the extension and source frame rate:

```json
{
  "extensionsUsed": ["ADM_animation_timing_v1"],
  "extensionsRequired": ["ADM_animation_timing_v1"],
  "extensions": {
    "ADM_animation_timing_v1": {
      "version": "1.0.0",
      "fps": 30,
      "fpsBase": 1.0
    }
  },
  "clips": [{
    "extensions": {
      "ADM_animation_timing_v1": {
        "frameStart": 1,
        "frameEnd": 32
      }
    }
  }]
}
```

The top-level extension object has exactly the required members `version`, `fps`, and `fpsBase`.
`version` MUST equal `"1.0.0"`. `fps` MUST be a positive integer; `fpsBase` MUST be finite and
greater than zero. The effective source frame rate is `fps / fpsBase`.

Every clip MUST contain this extension when the top-level extension is declared. Each per-clip
object has exactly the required members `frameStart` and `frameEnd`, both finite numbers, with
`frameEnd >= frameStart`. They are source timeline frame coordinates, not sample indices. The
clip's core `duration` MUST equal
`(frameEnd - frameStart) * fpsBase / fps` within the precision of the core duration encoding.
The first source frame corresponds to time zero; frame offsets are relative to that start.

Writers that promise exact source timeline reproduction MUST list the extension in both
`extensionsUsed` and `extensionsRequired`. Files that only need core playback in seconds MAY omit
the extension entirely. An implementation MUST reject malformed data and MUST reject an unknown
required extension under ADM §4.

## Import behavior

An authoring application that supports this extension SHOULD preserve the source frame rate and
frame-range span when importing. If it changes a project-wide frame rate to do so, it MUST expose
that change to the user. An explicit choice not to adopt the source frame rate MUST preserve core
animation times in seconds; the resulting local frame count may differ. If the extension is absent,
the source frame rate and frame range are unspecified and MUST NOT be inferred from duration.

## Conformance

An implementation claiming `ADM-ANIMATION-TIMING-1` MUST validate the frame-rate and range fields,
check their consistency with each clip's duration, and preserve the declared range on round trip.

- `ATIM-001`: preserve a 32-frame source range at 30 fps.
- `ATIM-002`: reject a frame range inconsistent with clip duration.
- `ATIM-003`: map core sample times to the source timeline without changing their seconds values.
- `ATIM-004`: report when source FPS is not applied or the current project rate is changed.
