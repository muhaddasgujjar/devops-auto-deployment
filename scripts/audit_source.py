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
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    snapshot = args.snapshot.resolve(strict=True)
    current_manifest = json.loads((root / "docs/evidence/source-sha256.json").read_text())
    foundation = {p: digest(root / p) == h for p, h in current_manifest.items()}
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
        "snapshot_clean": not bool(git(snapshot, "status", "--porcelain")),
        "foundation_hashes": foundation,
        "foundation_matches_recorded_evidence": all(foundation.values()),
        "foundation_runtime_matches_recorded_evidence": all(runtime.values()),
        "legacy_tracked_source": entries,
        "scope": "Read-only provenance inventory; no pipeline execution or compatibility validation",
        "decision": "Current Windows repository is authoritative for new work. Preserve the legacy snapshot; port reviewed components through explicit contract changes, never overlay its directories.",
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
