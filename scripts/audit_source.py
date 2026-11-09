"""Inventory the legacy lab without copying source or reading untracked secrets."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--foundation-ref", default="76057b1", help="Historical foundation Git commit")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    snapshot = args.snapshot.resolve(strict=True)
    current_manifest = json.loads((root / "docs/evidence/source-sha256.json").read_text())
    foundation = {p: hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(root), "show", args.foundation_ref + ":" + p])).hexdigest() == h
        for p, h in current_manifest.items()}
    runtime = {p: matched for p, matched in foundation.items() if p != "README.md"}
    # Only tracked application/config source is inventoried; never inspect lab secret directories.
    permitted = {"demo", "ci", "templates", "platform", "scripts", "docs"}
    entries = []
    for relative in git(snapshot, "ls-files").splitlines():
        rel = Path(relative)
        if not (rel.parts[0] in permitted or relative == "versions.json"):
            continue
        path = snapshot / rel
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(snapshot):
            raise RuntimeError("Snapshot entry escapes source boundary or is not a regular file")
        local = root / rel
        same = local.is_file() and digest(local) == digest(path)
        entries.append({"path": relative, "sha256": digest(path),
                        "current_checkout": "identical" if same else "different" if local.exists() else "absent"})
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_commit": git(snapshot, "rev-parse", "HEAD"),
        "foundation_reference": git(root, "rev-parse", args.foundation_ref),
        "snapshot_clean": not bool(git(snapshot, "status", "--porcelain")),
        "foundation_hashes": foundation,
        "foundation_matches_recorded_evidence": all(foundation.values()),
        "foundation_runtime_matches_recorded_evidence": all(runtime.values()),
        "legacy_tracked_source": entries,
        "scope": "Historical foundation commit and legacy snapshot provenance; current merged runtime is validated separately",
        "decision": "One merged source repository; canonical runtime demo/app.py, retained foundation example under examples/foundation.",
    }
    destination = root / "docs/evidence/source-reconciliation.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_commit": report["snapshot_commit"],
                      "snapshot_clean": report["snapshot_clean"],
                      "foundation_runtime_matches": all(runtime.values()),
                      "legacy_files": len(entries), "report": str(destination)}))
    return 0 if report["snapshot_clean"] and all(runtime.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
