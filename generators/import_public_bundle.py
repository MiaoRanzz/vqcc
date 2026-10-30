"""Reproduce pinned public circuit bytes without executing notebook code.

This imports compiled circuits, not their missing high-level generators. The
manifest must independently record the archive hash, exact member hashes,
source versions, licence decision and retained upstream notices.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import zipfile

from generate import output_workspace, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("dqi", "invsqrt", "dfthcsos"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if sha256(args.archive) != manifest["archive_sha256"]:
        raise ValueError("Archive does not match the reviewed source")
    task = manifest["tasks"][args.task]
    if task["reuse_decision"] != "eligible":
        raise ValueError("Unresolved source permission")
    entries = task["files"]
    outputs = [item["output"] for item in entries]
    if len(outputs) != len(set(outputs)):
        raise ValueError("Duplicate output name")
    for name in outputs:
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Output must be a flat task filename")
    with zipfile.ZipFile(args.archive) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate archive members")
        with output_workspace(args.output_dir) as (output, stage):
            for entry in entries:
                target = stage / entry["output"]
                with archive.open(entry["member"]) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest, 8 * 1024 * 1024)
                if sha256(target) != entry["sha256"]:
                    raise ValueError(f"Unexpected member bytes: {entry['member']}")
    code = output.parent / "code"
    code.mkdir(exist_ok=True)
    shutil.copy2(args.manifest, code / "public-manifest.json")
    report = {
        "kind": "pinned_public_artifact_import", "official_validation": False,
        "task": args.task, "created_at": datetime.now(timezone.utc).isoformat(),
        "archive": str(args.archive.resolve()), "archive_sha256": manifest["archive_sha256"],
        "manifest_sha256": sha256(args.manifest), "source": task,
        "source_generator_available": False,
        "recipe_sha256": sha256(Path(__file__)), "python_executable": sys.executable,
        "artifacts": [{"path": p.name, "sha256": sha256(p), "bytes": p.stat().st_size}
                      for p in sorted(output.iterdir())],
    }
    (output.parent / "generation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
