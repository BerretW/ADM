# Test local external assets

Use this optional headless catalog to check privately held assets with Blender
5.2 or later. It is an import smoke test, not interoperability certification.
It never copies external assets into the repository.

The catalog creates an in-memory triangle and imports the tracked ADM reference
triangle separately from external inputs. It scans only the immediate files in
the external directory, with case-insensitive extensions: `.fbx`, `.blend`,
`.adm`, and `.adm_anim`.

## Prepare inputs

1. Keep assets and their dependencies outside the repository, or use the
   ignored `adm_blender/tests/external_data/` directory. Do not commit them.
2. For each asset, create a UTF-8 JSON sidecar beside it. Name the sidecar by
   appending `.rights.json` to the complete asset filename. For example,
   `model.fbx` uses `model.fbx.rights.json`.
3. Record the source and license or rights basis, and explicitly confirm that
   you have permission to use the asset and its dependencies in local tests:

   ```json
   {
     "asset": "model.fbx",
     "source": "Creator or source URL",
     "license": "License name or description of permission",
     "permission_for_local_testing": true
   }
   ```

The `asset` value must match the filename exactly. Fill in the actual source
and rights basis; don't use the example text as evidence of permission.
Missing, invalid, or unclear sidecars result in a skip. The sidecar is your
attestation, not a legal verification by the test. Ensure dependencies such as
textures have the same permission. Sidecars are ignored by Git.

## Run the catalog

From the repository root, run:

```powershell
blender -b --factory-startup --disable-autoexec --python adm_blender\tests\test_external_assets_blender.py
```

To select a directory outside the repository, append
`-- --external-dir "ASSET_DIRECTORY"` and replace `ASSET_DIRECTORY` with its
path. Disable automatic script execution as shown, and run only assets you trust.
The default directory is ignored by Git; arbitrary directories are not
necessarily ignored.

Each result includes `PASS`, `FAIL`, or `SKIP` and a reason. Missing formats
produce `SKIP: FORMAT: ...`. A run with only passes and skips exits 0; a
processing failure exits 1. Confirm all four external formats report a skip
when the directory is empty.

FBX uses Blender's general FBX importer. BLEND appends objects without opening
the file as the active project. ADM is validated and imported. ADM_ANIM is
validated, but binding and import are skipped because this catalog does not
configure a compatible target. A validation pass does not imply a binding pass.
Use the dedicated animation tests for target-binding coverage.
