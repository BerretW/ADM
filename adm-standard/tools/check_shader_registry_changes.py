#!/usr/bin/env python3
"""Validate shader registry integrity and recorded development changes."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHADERS = ROOT / "adm-standard" / "shaders"
REGISTRY_PATH = "adm-standard/shaders/registry.json"
REVISION_PATH = "adm-standard/shaders/revisions.json"
FREEZE_PATH = "adm-standard/shaders/freeze-2026-11-15.json"
CHANGELOG_PATH = ROOT / "adm-standard" / "CHANGELOG.md"
IDENTITY = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+@\d+\.\d+\.\d+")
HASH = re.compile(r"[0-9a-f]{64}")


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _heading_slug(text):
    return re.sub(r"[^\w -]", "", text.lower()).replace(" ", "-")


def contract_digest_text(reference, text):
    _, _, anchor = reference.partition("#")
    if not anchor:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    lines = text.splitlines(keepends=True)
    headings = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((index, len(match.group(1)), _heading_slug(match.group(2))))
    matches = [(index, level) for index, level, slug in headings if slug == anchor]
    if len(matches) != 1:
        raise ValueError(f"contract anchor {reference!r} must identify exactly one heading")
    start, level = matches[0]
    end = next((index for index, other_level, _ in headings
                if index > start and other_level <= level), len(lines))
    return hashlib.sha256("".join(lines[start:end]).encode("utf-8")).hexdigest()


def contract_digest(reference, shader_dir):
    path = reference.partition("#")[0]
    return contract_digest_text(reference, (shader_dir / path).read_text(encoding="utf-8"))


def _registry_snapshot(registry, contract_loader):
    profiles = {}
    contracts = {}
    for entry in registry["shaders"]:
        identity = f'{entry["id"]}@{entry["version"]}'
        if not IDENTITY.fullmatch(identity):
            raise ValueError(f"invalid shader identity: {identity}")
        if identity in profiles:
            raise ValueError(f"duplicate shader identity: {identity}")
        reference = entry["contract"]
        profiles[identity] = digest(entry)
        contracts[reference] = contract_digest_text(reference, contract_loader(reference))
    return profiles, contracts


def verify_registry(registry, shader_dir):
    profiles, contracts = _registry_snapshot(
        registry,
        lambda reference: (shader_dir / reference.partition("#")[0]).read_text(encoding="utf-8"),
    )
    return profiles, contracts


def validate_revision_log(revision_log, changelog_text):
    records = revision_log["records"]
    if not isinstance(records, list):
        raise ValueError("shader revision log records must be an array")
    seen = set()
    headings = {_heading_slug(match.group(1)) for match in
                re.finditer(r"^#{1,6}\s+(.+?)\s*$", changelog_text, re.MULTILINE)}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("shader revision records must be objects")
        record_id = record.get("id")
        if not isinstance(record_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record_id):
            raise ValueError("shader revision record has an invalid id")
        if record_id in seen:
            raise ValueError(f"duplicate shader revision record: {record_id}")
        seen.add(record_id)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record.get("date", "")):
            raise ValueError(f"shader revision {record_id} has an invalid date")
        if not isinstance(record.get("summary"), str) or not record["summary"].strip():
            raise ValueError(f"shader revision {record_id} needs a summary")
        link = record.get("changelog", "")
        if not isinstance(link, str) or "#" not in link:
            raise ValueError(f"shader revision {record_id} needs a changelog heading link")
        path, anchor = link.split("#", 1)
        if path != "CHANGELOG.md" or anchor not in headings:
            raise ValueError(f"shader revision {record_id} links to a missing changelog heading")
        profiles = record.get("profiles")
        contracts = record.get("contracts")
        if not isinstance(profiles, list) or not isinstance(contracts, list):
            raise ValueError(f"shader revision {record_id} needs profile and contract arrays")
        if not profiles and not contracts:
            raise ValueError(f"shader revision {record_id} must identify a changed profile or contract")
        if any(not isinstance(value, str) or not IDENTITY.fullmatch(value) for value in profiles):
            raise ValueError(f"shader revision {record_id} has an invalid profile identity")
        if any(not isinstance(value, str) or not value.strip() for value in contracts):
            raise ValueError(f"shader revision {record_id} has an invalid contract reference")
        if len(profiles) != len(set(profiles)) or len(contracts) != len(set(contracts)):
            raise ValueError(f"shader revision {record_id} contains duplicate references")
    return records


def verify_revision_history(current, previous):
    current_records = current["records"]
    previous_records = previous["records"]
    if current_records[:len(previous_records)] != previous_records:
        raise ValueError("shader revision history changed or removed an existing record")
    return current_records[len(previous_records):]


def verify_historical_freeze_history(current, previous):
    problems = []
    for section in ("profiles", "contracts"):
        for key, value in previous[section].items():
            if current[section].get(key) != value:
                problems.append(f"historical shader publication record changed or removed: {key}")
    if problems:
        raise ValueError("\n".join(sorted(problems)))


def verify_recorded_changes(changed_profiles, changed_contracts, new_records):
    recorded_profiles = {profile for record in new_records for profile in record["profiles"]}
    recorded_contracts = {contract for record in new_records for contract in record["contracts"]}
    missing_profiles = set(changed_profiles) - recorded_profiles
    missing_contracts = set(changed_contracts) - recorded_contracts
    unexpected_profiles = recorded_profiles - set(changed_profiles)
    unexpected_contracts = recorded_contracts - set(changed_contracts)
    problems = []
    if missing_profiles:
        problems.append("unrecorded shader profiles: " + ", ".join(sorted(missing_profiles)))
    if missing_contracts:
        problems.append("unrecorded shader contracts: " + ", ".join(sorted(missing_contracts)))
    if unexpected_profiles:
        problems.append("recorded but unchanged shader profiles: " + ", ".join(sorted(unexpected_profiles)))
    if unexpected_contracts:
        problems.append("recorded but unchanged shader contracts: " + ", ".join(sorted(unexpected_contracts)))
    if problems:
        raise ValueError("\n".join(problems))


def _git_show(revision, path):
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


def _optional_git_json(revision, path):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}:{path}"], cwd=ROOT,
        capture_output=True, text=True,
    )
    if result.returncode:
        return None
    return json.loads(_git_show(revision, path))


def _contract_at_revision(reference, revision):
    relative = (SHADERS / reference.partition("#")[0]).resolve().relative_to(ROOT)
    return _git_show(revision, str(relative).replace("\\", "/"))


def verify_git_changes(registry, revision_log, base_revision):
    if not base_revision or set(base_revision) == {"0"}:
        print("No base revision available; shader development-change comparison skipped")
        return
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base_revision):
        raise ValueError("base revision must be a full Git commit hash")
    subprocess.run(["git", "cat-file", "-e", f"{base_revision}^{{commit}}"],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    old_registry = _optional_git_json(base_revision, REGISTRY_PATH)
    old_revision_log = _optional_git_json(base_revision, REVISION_PATH) or {"records": []}
    old_freeze = _optional_git_json(base_revision, FREEZE_PATH)
    if old_registry is None:
        print("Base revision predates the shader registry; change comparison skipped")
        return
    if old_freeze is not None:
        verify_historical_freeze_history(
            verify_historical_freeze(SHADERS / "freeze-2026-11-15.json"), old_freeze,
        )
    previous_records = validate_revision_log(old_revision_log, CHANGELOG_PATH.read_text(encoding="utf-8"))
    new_records = verify_revision_history(revision_log, {"records": previous_records})
    old_profiles, old_contracts = _registry_snapshot(
        old_registry, lambda reference: _contract_at_revision(reference, base_revision),
    )
    new_profiles, new_contracts = verify_registry(registry, SHADERS)
    changed_profiles = {
        identity for identity in old_profiles.keys() | new_profiles.keys()
        if old_profiles.get(identity) != new_profiles.get(identity)
    }
    changed_contracts = {
        reference for reference in old_contracts.keys() | new_contracts.keys()
        if old_contracts.get(reference) != new_contracts.get(reference)
    }
    verify_recorded_changes(changed_profiles, changed_contracts, new_records)
    print(f"PASS shader changes recorded against {base_revision}")


def verify_historical_freeze(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    for section in ("profiles", "contracts"):
        values = record.get(section)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"historical shader publication record has invalid {section}")
        if any(not isinstance(value, str) or not HASH.fullmatch(value)
               for value in values.values()):
            raise ValueError(f"historical shader publication record has invalid {section} hash")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-revision-env", help="environment variable containing the CI base commit")
    args = parser.parse_args()
    registry = json.loads((SHADERS / "registry.json").read_text(encoding="utf-8"))
    revision_log = json.loads((SHADERS / "revisions.json").read_text(encoding="utf-8"))
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    profiles, _ = verify_registry(registry, SHADERS)
    validate_revision_log(revision_log, changelog)
    verify_historical_freeze(SHADERS / "freeze-2026-11-15.json")
    if args.base_revision_env:
        verify_git_changes(registry, revision_log, os.environ.get(args.base_revision_env, ""))
    print(f"PASS shader registry integrity ({len(profiles)} profiles)")
    print("PASS historical 2026-11-15 shader publication record")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"FAIL shader registry integrity: {exc}", file=sys.stderr)
        sys.exit(1)
