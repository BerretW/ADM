# `ADM_animation_timing_v1`

This normative ADM 1.0 extension preserves the project frame rate and each clip's frame rate and
frame range alongside the core animation duration in seconds. Its schema version is `1.1.0`; its
capability is `ADM-ANIMATION-TIMING-1`. Changing a clip's frame rate while keeping its frame range
changes its duration and playback speed. The extension does not change sample values or interpolation.

## Declaration and data

The top-level `.adm_anim` manifest declares the extension and project frame rate:

```json
{
  "extensionsUsed": ["ADM_animation_timing_v1"],
  "extensionsRequired": ["ADM_animation_timing_v1"],
  "extensions": {
    "ADM_animation_timing_v1": {
      "version": "1.1.0",
      "fps": 30,
      "fpsBase": 1.0
    }
  },
  "clips": [{
    "extensions": {
      "ADM_animation_timing_v1": {
        "frameStart": 1,
        "frameEnd": 32,
        "fps": 30,
        "fpsBase": 1.0
      }
    }
  }]
}
```

The top-level extension object has exactly the required members `version`, `fps`, and `fpsBase`.
`version` MUST equal `"1.1.0"`. The top-level `fps` and `fpsBase` record the project frame rate.
`fps` MUST be a positive integer; `fpsBase` MUST be finite and greater than zero. The effective
project frame rate is `fps / fpsBase`.

Every clip MUST contain this extension when the top-level extension is declared. Each per-clip
object has exactly the required members `frameStart`, `frameEnd`, `fps`, and `fpsBase`.
`frameStart` and `frameEnd` are finite source timeline frame coordinates, not sample indices, and
`frameEnd >= frameStart`. Per-clip `fps` MUST be a positive integer; per-clip `fpsBase` MUST be
finite and greater than zero. The effective clip frame rate is `fps / fpsBase`. The clip's core
`duration` MUST equal `(frameEnd - frameStart) * fpsBase / fps` within the precision of the core
duration encoding. The first source frame corresponds to time zero; frame offsets are relative to
that start.

The project frame rate does not override a clip's frame rate. A reader that preserves source frame
ranges MUST use each clip's rate when mapping sample times to frames. When multiple clips use
different rates, an authoring application with one project-wide playback rate MAY change that rate
when the active clip changes; it MUST expose the change to the user.

Writers that promise exact source timeline reproduction MUST list the extension in both
`extensionsUsed` and `extensionsRequired`. Files that only need core playback in seconds MAY omit
the extension entirely. An implementation MUST reject malformed data and MUST reject an unknown
required extension under ADM §4.
The `1.0.0` form of this extension did not include per-clip rates and is not accepted as `1.1.0`;
older development files are not automatically migrated.

## Import behavior

An authoring application that supports this extension SHOULD preserve each clip's frame rate and
frame-range span when importing. An explicit choice not to adopt a clip's frame rate MUST preserve
core animation times in seconds; the resulting local frame count may differ. If the extension is
absent, the source frame rate and frame range are unspecified and MUST NOT be inferred from duration.

## Conformance

An implementation claiming `ADM-ANIMATION-TIMING-1` MUST validate the project and per-clip frame-rate
and range fields, check each clip's consistency with its duration, and preserve the declared rate
and range on round trip.

- `ATIM-001`: preserve a 32-frame source range at 30 fps.
- `ATIM-002`: reject a frame range inconsistent with clip duration.
- `ATIM-003`: map core sample times to the source timeline without changing their seconds values.
- `ATIM-004`: report when source FPS is not applied or the current project rate is changed.
- `ATIM-005`: preserve different source frame rates in clips in one library.
