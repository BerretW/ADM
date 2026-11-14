# ADM Tools for Blender

Author, import, export and validate **ADM Draft 0.4** model assets (`.adm`) and standalone animation
libraries (`.adm_anim`) in **Blender 5.2+**.

The add-on uses a Sollumz-inspired create/convert workflow, with an ADM sidebar, explicit object
types, skeleton role mapping, materials, animation libraries and validation reports. This is an
independent project, not affiliated with Sollumz.

**Status:** working implementation against a working draft, not certified ADM 1.0 conformance.
Draft 0.3 files are intentionally incompatible with the current chunk container.

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
| [adm-standard](adm-standard/) | Draft 0.4 specification, fixtures and reference container tools |
| [adm_blender/tests](adm_blender/tests/) | Container, semantic and Blender round-trip tests |

Supported authoring includes meshes, skins, morph targets, semantic skeleton profiles, facial bindings,
IK descriptors, LODs, attachment sockets, shader parameter definitions/tracks, model components,
physical materials, per-triangle collision surfaces, and bone-linked hitboxes. External texture
sidecars are optional; embedded textures remain the default.

### Important limits

- RAW chunk storage is supported; optional ZSTD decoding is not.
- Textures export as PNG by default (any source format is converted). KTX2 or DDS (RGBA8/BC1/BC3)
  can be chosen at export and always carry an embedded PNG fallback; Basis Universal and BC7 are not supported.
- All 20 official shader profiles have a Blender viewport preview. Their parameters drive the node tree,
  and the export keeps the portable PBR fallback. Skin, fur and fabric previews are approximations.
  Custom shaders use a reported PBR fallback, and certified renderer conformance is not claimed.
- `ADM_vertex_control_v1` transports `COLOR_0`/`COLOR_1`, palette references, and material control
  values. `COLOR_0` drives the Blender preview and its four parameters can be animated. For all Core 20
  profiles, `COLOR_1` is explicitly reserved, has no shading effect, and is preserved for round-trip
  editing. The F0 graph has Blender bake coverage, but independent-renderer conformance is not claimed.
  See the `SPEC_GAP-SHADER-CORE20` entry before relying on renderer interoperability.
- External-image and per-triangle physical-surface round trips have Blender workflow coverage, but
  security-edge cases and independent-reader interoperability remain open.
- Vehicle/weapon profile names remain provisional. Physics, damage and other gameplay behavior
  are outside this asset format.
- Skeleton profiles: `humanoid.vrm1` is fully supported. Quadruped profiles (`animal.*.v1`) are
  PROVISIONAL proposals and are not certifiable. See [SPEC_GAPS.md](adm-standard/SPEC_GAPS.md).

See the [draft](adm-standard/ADM-1.0-SPEC.md) and [implementation limits](adm_blender/README.md#draft-04-container-and-fallback)
before making interoperability or conformance claims.

## Development and tests

The core and reference tests require **Python 3.11+**, with no third-party packages. The KTX2/DDS
codec test (`test_gputex`) additionally needs NumPy (`pip install numpy`).
Blender supplies its own Python, `bpy` and NumPy for add-on tests.

Run from the repository root:

```powershell
python -m unittest adm_blender.tests.test_skeleton_profiles adm_blender.tests.test_container adm_blender.tests.test_draft4 adm_blender.tests.test_gputex -v
python .\adm-standard\tools\run_tests.py
```

Run Blender round trips separately:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_fixtures.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_workflow.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_skeleton_blender.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_material_slots.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_texture_formats.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\build_material_test_scene.py -- .\dist\ADM_Core20_Material_Test_Scene.blend
```

The last command builds a labelled 20-swatch viewport scene from the registered shader profiles,
with deterministic textures, vertex controls and `COLOR_1` test attributes.

The [CI workflow](.github/workflows/ci.yml) runs core/reference tests and verifies fixture regeneration
on Windows and Linux. A separate Ubuntu job downloads Blender 5.2.4, verifies its pinned SHA-256, and
runs the headless Blender integration scripts. This does not certify independent renderer/IK
conformance.

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
