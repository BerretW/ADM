# ADM Tools for Blender

Author, import, export and validate **ADM 1.0** model assets (`.adm`) and standalone animation
libraries (`.adm_anim`) in **Blender 5.2+**.

The add-on uses a Sollumz-inspired create/convert workflow, with an ADM sidebar, explicit object
types, skeleton role mapping, materials, animation libraries and validation reports. This is an
independent project, not affiliated with Sollumz.

**Status:** working reference implementation against the final ADM 1.0 specification; independent conformance certification is not implied.
Legacy ADM, ADS and `.ads_anim` files are intentionally incompatible with the ADM 1.0 chunk container.

## Install

1. Download the repository and extract it.
2. Zip **only the `adm_blender` folder**, not the whole repository.
3. In Blender, choose **Edit > Preferences > Get Extensions > Install from Disk**, select that ZIP
   and enable ADM Tools.
4. Open the **ADM** tab in the 3D View sidebar (`N`).

Alternatively, build the extension from the repository root (PowerShell example):

```powershell
New-Item -ItemType Directory -Force .\dist | Out-Null
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --command extension build --source-dir .\adm_blender --output-dir .\dist
```

Install the generated ZIP from `dist`. The build excludes tests and Python caches.

See the [add-on guide](adm_blender/README.md) for authoring, import/export and animation workflows.

## Included

| Path | Contents |
| --- | --- |
| [adm_blender](adm_blender/) | Blender extension and independent Python parsing/validation core |
| [adm-standard](adm-standard/) | Final ADM 1.0 specification, fixtures and reference container tools |
| [adm_blender/tests](adm_blender/tests/) | Container, semantic and Blender round-trip tests |

Supported authoring includes meshes, skins, morph targets, semantic skeleton profiles, facial bindings,
IK descriptors, LODs, attachment sockets, shader parameter definitions/tracks, model components,
physical materials, per-triangle collision surfaces, stable interactive display surfaces, and
bone-linked hitboxes. External texture sidecars are optional; embedded textures remain the default.
`ADM-HUMANOID-SOCKETS-1` standardizes equipment attachment frames without changing humanoid skeleton
roles or animation compatibility.

### Important limits

- RAW chunk storage is supported; optional ZSTD decoding is not.
- Textures export as PNG by default (any source format is converted). KTX2 or DDS (RGBA8/BC1/BC3)
  can be chosen at export and always carry an embedded PNG fallback; Basis Universal and BC7 are not supported.
- The original 20 shader profiles have a Blender viewport preview. Their parameters drive the node tree,
  and the export keeps the portable PBR fallback. Skin, fur and fabric previews are approximations.
  Custom shaders use a reported PBR fallback, and certified renderer conformance is not claimed.
- `adm.surface.interactive@1.0.0` and `ADM-INTERACTIVE-SURFACES-1` identify dynamic displays on
  geometry. Blender previews the static authored fallback; runtime images, interaction and
  independent renderer certification remain outside the add-on.
- `ADM_vertex_control_v1` transports `COLOR_0`/`COLOR_1`, palette references, and material control
  values. `COLOR_0` drives the Blender preview and its four parameters can be animated. For all Core 20
  `1.0.0` profiles, `COLOR_1` remains reserved and has no shading effect. The compatible `2.0.0`
  profiles activate the documented channel masks; Blender provides shader-aware painting and preview.
  The F0 graph has Blender bake coverage, but independent-renderer conformance is not claimed.
  See the `SPEC_GAP-SHADER-CORE20` entry before relying on renderer interoperability.
- External-image and per-triangle physical-surface round trips have Blender workflow coverage, but
  security-edge cases and independent-reader interoperability remain open.
- Vehicle/weapon profiles are normative ADM 1.0 annexes; independent profile certification is
  separate. Physics, damage and other gameplay behavior are outside this asset format.
- `humanoid.vrm1` is the normative semantic skeleton profile. Quadruped profiles (`animal.*.v1`)
  are proposals outside ADM 1.0; see [SPEC_GAPS.md](adm-standard/SPEC_GAPS.md).

See the [final specification](adm-standard/ADM-1.0-SPEC.md) and [implementation limits](adm_blender/README.md#adm-10-container-and-fallback)
before making interoperability or conformance claims.

## Development and tests

The core and reference tests require **Python 3.11+**, with no third-party packages. The KTX2/DDS
codec test (`test_gputex`) additionally needs NumPy (`pip install numpy`).
Blender supplies its own Python, `bpy` and NumPy for add-on tests.

Run from the repository root:

```powershell
python -m unittest adm_blender.tests.test_skeleton_profiles adm_blender.tests.test_container adm_blender.tests.test_draft4 adm_blender.tests.test_gputex -v
python .\adm-standard\tools\run_tests.py
python .\adm-standard\tools\test_interactive_surfaces.py
python .\adm-standard\tools\test_shader_vertex_masks.py
python .\adm-standard\tools\test_independent_conformance.py
```

Run Blender round trips separately:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_fixtures.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_interactive_blender.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_workflow.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_skeleton_blender.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_material_slots.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_texture_formats.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\build_material_test_scene.py -- .\dist\ADM_Color1_V2_Material_Test_Scene.blend
```

The last command builds a labelled preview scene for all 20 `2.0.0` profiles at mask values
`0`, `0.25`, `0.5`, `0.75` and `1.0` (100 swatches), with deterministic textures and vertex controls.

The [CI workflow](.github/workflows/ci.yml) runs core/reference tests and verifies fixture regeneration
on Windows and Linux. A separate Ubuntu job tries Blender's download host and two mirrors, verifies the
same pinned Blender 5.2.4 SHA-256 for each successful download, and runs headless Blender integration
scripts. This does not certify independent renderer/IK conformance.

## Publishing

This workspace does not require a GitHub integration or stored credentials. Create your own repository
and upload the sources, or initialize Git locally and add your chosen remote. Do not upload `.venv`,
caches, logs, credentials or generated packages; the root `.gitignore` covers common local artifacts.
The ADM binary fixtures **must remain included**.

For a downloadable release, build the extension as above and attach the resulting ZIP to your GitHub
Release. Users should install that extension ZIP, not GitHub's whole-repository source ZIP.

## License

- **Code:** [MIT](LICENSE), including the Blender extension and reference Python tools.
- **Specification, standard-kit documentation and reference fixtures:** [CC0-1.0](adm-standard/LICENSE).

The licenses do not change the license or ownership of assets users create or import. Referenced
third-party standards remain under their respective terms.
