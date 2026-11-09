"""Render a constrained environment directory. Never accepts tags or arbitrary YAML."""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(r"[a-z0-9][a-z0-9.:-]*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def render(image, commit, output, baseline=False):
    if not IMAGE.fullmatch(image):
        raise ValueError("image must be a repository@sha256:<64 lowercase hex> reference")
    if not COMMIT.fullmatch(commit):
        raise ValueError("commit must be a full lowercase Git SHA")
    source = ROOT / "templates" / ("baseline" if baseline else "release")
    rendered = {}
    for path in sorted(source.glob("*.yaml")):
        content = path.read_text(encoding="utf-8").replace("__IMAGE__", image).replace("__COMMIT__", commit)
        if "__IMAGE__" in content or "__COMMIT__" in content:
            raise ValueError("unresolved template marker")
        rendered[path.name] = content
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")
    return list(rendered)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    try:
        render(args.image, args.commit, args.output, args.baseline)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
