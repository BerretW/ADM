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
physical materials and bone-linked hitboxes.

### Important limits

- RAW chunk storage is supported; optional ZSTD decoding is not.
- KTX2 textures use their required embedded PNG/JPEG fallback.
- Non-core shaders use an explicitly reported PBR preview fallback. Their metadata and parameter
  tracks are preserved; exact custom/layered shader rendering is not claimed.
- Vehicle/weapon profile names remain provisional. Physics, damage and other gameplay behavior
  are outside this asset format.

See the [draft](adm-standard/ADM-1.0-SPEC.md) and [implementation limits](adm_blender/README.md#draft-04-container-and-fallback)
before making interoperability or conformance claims.

## Development and tests

The core and reference tests require **Python 3.11+**, with no third-party packages.
Blender supplies its own Python, `bpy` and NumPy for add-on tests.

Run from the repository root:

```powershell
python -m unittest adm_blender.tests.test_container adm_blender.tests.test_draft4 -v
python .\adm-standard\tools\run_tests.py
```

Run Blender round trips separately:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_fixtures.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python-exit-code 1 --python .\adm_blender\tests\test_workflow.py
```

The [CI workflow](.github/workflows/ci.yml) runs core/reference tests and verifies fixture regeneration
on Windows and Linux. It does not install Blender or certify numerical rendering/IK conformance.

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
