#!/usr/bin/env python3
"""Check that the reference-test catalog names real fixtures, expectations and tests."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "adm-standard" / "fixtures" / "reference-catalog.json"
EXPECTED_CATEGORIES = {
    "static-model",
    "material-test",
    "humanoid",
    "animation",
    "modular-vehicle",
    "modular-weapon",
    "interactive-surface",
    "terrain",
}


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    categories = catalog["categories"]
    ids = [category["id"] for category in categories]
    if set(ids) != EXPECTED_CATEGORIES or len(ids) != len(set(ids)):
        raise ValueError("reference catalog must define each required category exactly once")
    if catalog["independentImplementationsVerified"] != 0 or catalog["interoperabilityClaim"]:
        raise ValueError("catalog must not claim unverified independent interoperability")
    for category in categories:
        if category["status"] not in {"partial", "planned", "implemented"}:
            raise ValueError(f'{category["id"]}: invalid implementation status')
        for field in ("verifiedChecks", "notTested", "requiredFixtureData", "requiredExpectationFields"):
            if not isinstance(category[field], list) or not category[field]:
                raise ValueError(f'{category["id"]}: missing {field} status')
        for field in ("fixtures", "expectations", "referenceTests"):
            for relative_path in category[field]:
                path = (ROOT / relative_path).resolve()
                if ROOT not in path.parents or not path.is_file():
                    raise ValueError(f'{category["id"]}: missing or out-of-repository {field}: {relative_path}')
    print(f"PASS reference-test catalog ({len(categories)} categories; no interoperability claim)")


if __name__ == "__main__":
    main()
