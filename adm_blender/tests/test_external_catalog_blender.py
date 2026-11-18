"""Exercise external catalog outcomes using repository reference assets."""

import contextlib
import io
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import adm_blender  # noqa: E402
from adm_blender.tests import test_external_assets_blender as catalog  # noqa: E402


def main():
    adm_blender.register()
    fixtures = REPO / "adm-standard" / "fixtures" / "valid"
    model = fixtures / "triangle.adm"
    animation = fixtures / "catalog-only.adm_anim"
    files = {"FBX": [Path("unapproved.fbx")], "BLEND": [],
             "ADM": [model], "ADM_ANIM": [animation]}
    output = io.StringIO()
    with patch.object(catalog.adm_blender, "register"), \
            patch.object(catalog, "discover", return_value=files), \
            patch.object(catalog, "permission",
                         side_effect=lambda path: (path != files["FBX"][0], "no permission")), \
            patch.object(catalog, "process", wraps=catalog.process) as process, \
            contextlib.redirect_stdout(output):
        failures = catalog.run(Path("unused"))
    text = output.getvalue()
    print(text)
    assert failures == 0
    assert "SKIP: FBX: unapproved.fbx: no permission" in text
    assert "SKIP: BLEND:" in text
    assert "PASS: ADM: triangle.adm: validated and imported" in text
    assert "PASS: ADM_ANIM validation (catalog-only.adm_anim):" in text
    assert "SKIP: ADM_ANIM: catalog-only.adm_anim: binding/import not tested" in text
    assert [call.args[1] for call in process.call_args_list] == [model, animation]

    bad = REPO / "adm-standard" / "fixtures" / "invalid" / "bad_hash.adm"
    with patch.object(catalog.adm_blender, "register"), \
            patch.object(catalog, "discover", return_value={"ADM": [bad]}), \
            patch.object(catalog, "permission", return_value=(True, "approved")), \
            contextlib.redirect_stdout(io.StringIO()) as output, \
            contextlib.redirect_stderr(io.StringIO()):
        failures = catalog.run(Path("unused"))
    assert failures == 1
    assert "FAIL: ADM: bad_hash.adm:" in output.getvalue()


if __name__ == "__main__":
    try:
        main()
        print("PASS: external catalog regression: rights gating, import, and binding skip")
        code = 0
    except Exception:
        traceback.print_exc()
        print("FAIL: external catalog regression")
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
