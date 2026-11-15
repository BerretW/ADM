#!/usr/bin/env python3
"""Check published shader identities against the reviewed freeze baseline."""
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


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def contract_digest(reference, shader_dir):
    path, _, anchor = reference.partition("#")
    text = (shader_dir / path).read_text(encoding="utf-8")
    if anchor:
        lines = text.splitlines(keepends=True)
        headings = []
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                slug = re.sub(r"[^\w -]", "", match.group(2).lower()).replace(" ", "-")
                headings.append((index, len(match.group(1)), slug))
        matches = [(index, level) for index, level, slug in headings if slug == anchor]
        if len(matches) != 1:
            raise ValueError(f"contract anchor {reference!r} must identify exactly one heading")
        start, level = matches[0]
        end = next((index for index, other_level, _ in headings
                    if index > start and other_level <= level), len(lines))
        text = "".join(lines[start:end])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_freeze(registry, baseline, contracts):
    profiles = {}
    for entry in registry["shaders"]:
        identity = f'{entry["id"]}@{entry["version"]}'
        if identity in profiles:
            raise ValueError(f"duplicate shader identity: {identity}")
        profiles[identity] = digest(entry)

    problems = []
    for identity, expected in baseline["profiles"].items():
        if identity not in profiles:
            problems.append(f"published shader removed: {identity}")
        elif profiles[identity] != expected:
            problems.append(f"published shader changed without a new version: {identity}")
    for identity in profiles.keys() - baseline["profiles"].keys():
        problems.append(f"new shader needs a reviewed freeze entry: {identity}")
    for reference, expected in baseline["contracts"].items():
        if reference not in contracts:
            problems.append(f"published shader contract removed: {reference}")
        elif contracts[reference] != expected:
            problems.append(f"published shader contract changed: {reference}")
    for reference in contracts.keys() - baseline["contracts"].keys():
        problems.append(f"new shader contract needs a reviewed freeze entry: {reference}")
    if problems:
        raise ValueError("\n".join(sorted(problems)))


def verify_baseline_history(baseline, previous):
    problems = []
    for section in ("profiles", "contracts"):
        for key, value in previous[section].items():
            if baseline[section].get(key) != value:
                problems.append(f"published freeze record changed or removed: {key}")
    if problems:
        raise ValueError("\n".join(sorted(problems)))


def verify_git_history(baseline, revision):
    if not revision or set(revision) == {"0"}:
        print("No base revision available; baseline history check skipped")
        return
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        raise ValueError("base revision must be a full Git commit hash")
    path = "adm-standard/shaders/freeze-2026-11-15.json"
    subprocess.run(["git", "cat-file", "-e", f"{revision}^{{commit}}"],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    tree = subprocess.run(["git", "ls-tree", "--name-only", revision, "--", path],
                          cwd=ROOT, check=True, capture_output=True, text=True)
    if not tree.stdout.strip():
        print("Base revision predates the freeze record; baseline history check skipped")
        return
    previous = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=ROOT,
                              check=True, capture_output=True, text=True, encoding="utf-8")
    verify_baseline_history(baseline, json.loads(previous.stdout))
    print("PASS shader freeze record is append-only against base revision")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-revision-env", help="environment variable containing the CI base commit")
    args = parser.parse_args()
    registry = json.loads((SHADERS / "registry.json").read_text(encoding="utf-8"))
    baseline = json.loads((SHADERS / "freeze-2026-11-15.json").read_text(encoding="utf-8"))
    contracts = {entry["contract"]: contract_digest(entry["contract"], SHADERS)
                 for entry in registry["shaders"]}
    verify_freeze(registry, baseline, contracts)
    if args.base_revision_env:
        verify_git_history(baseline, os.environ.get(args.base_revision_env, ""))
    print(f"PASS frozen shader registry ({len(registry['shaders'])} profiles)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"FAIL shader registry freeze: {exc}", file=sys.stderr)
        sys.exit(1)
