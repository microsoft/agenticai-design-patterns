"""Validate assets and generate the README catalog.

Usage:
    python tools/assets.py validate
    python tools/assets.py catalog [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SCHEMA = ROOT / "schema" / "manifest.schema.json"
README = ROOT / "README.md"

REQUIRED_FILES = ("manifest.yaml", "README.md", "CHANGELOG.md")
REQUIRED_README_HEADINGS = ("## When to use", "## Getting started")
MAX_FILE_BYTES = 10 * 1024 * 1024
BLOCKED_SUFFIXES = {".pfx", ".p12", ".pem", ".key", ".env", ".publishsettings"}
TEXT_SUFFIXES = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".ipynb", ".ts", ".js", ".cs", ".java",
    ".go", ".ps1", ".sh", ".bicep", ".tf", ".tfvars", ".toml", ".ini", ".cfg", ".xml",
    ".html", ".csv", ".sample", ".mmd", ".drawio",
}

# Heuristics for content that must not be published. They catch common mistakes; they do
# not replace curator review or GitHub secret scanning.
BLOCKED_PATTERNS = {
    "internal SharePoint URL": re.compile(r"https?://[a-z0-9-]+(?:-my)?\.sharepoint\.com/", re.I),
    "internal corpnet host": re.compile(r"\b[a-z0-9.-]+\.corp\.microsoft\.com\b", re.I),
    "confidentiality marking": re.compile(r"\b(?:Microsoft (?:Highly )?Confidential|Internal Use Only)\b", re.I),
    "storage account key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "SAS token signature": re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest.yaml must contain a mapping")
    # YAML parses unquoted dates into date objects; the schema expects strings.
    return json.loads(json.dumps(data, default=str))


def asset_dirs() -> list[Path]:
    if not ASSETS.is_dir():
        return []
    return sorted(p for p in ASSETS.iterdir() if p.is_dir() and not p.name.startswith("."))


def scan_files(asset: Path, errors: list[str]) -> None:
    for path in sorted(asset.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{rel}: larger than 10 MB; publish it as a release attachment instead")
        if path.suffix.lower() in BLOCKED_SUFFIXES or path.name.lower() == ".env":
            errors.append(f"{rel}: file type not allowed (possible secret)")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != "Dockerfile":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in BLOCKED_PATTERNS.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{rel}:{line}: possible {label}")


def validate() -> int:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    errors: list[str] = []
    manifests: dict[str, dict] = {}

    for asset in asset_dirs():
        name = asset.name
        missing = [f for f in REQUIRED_FILES if not (asset / f).is_file()]
        if missing:
            errors.append(f"assets/{name}: missing {', '.join(missing)}")
        if (asset / "manifest.yaml").is_file():
            try:
                manifest = load_manifest(asset / "manifest.yaml")
            except (yaml.YAMLError, ValueError) as exc:
                errors.append(f"assets/{name}/manifest.yaml: {exc}")
            else:
                for err in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
                    where = "/".join(str(p) for p in err.path) or "(root)"
                    message = err.message
                    if err.validator == "not":
                        message = "deprecated_by is only allowed when maturity is 'deprecated'"
                    errors.append(f"assets/{name}/manifest.yaml: {where}: {message}")
                if manifest.get("id") != name:
                    errors.append(f"assets/{name}/manifest.yaml: id must equal the folder name '{name}'")
                manifests[name] = manifest
        readme = asset / "README.md"
        if readme.is_file():
            content = readme.read_text(encoding="utf-8")
            if not re.search(r"^# \S", content, re.M):
                errors.append(f"assets/{name}/README.md: needs a level-1 title")
            for heading in REQUIRED_README_HEADINGS:
                if not re.search(rf"^{re.escape(heading)}\s*$", content, re.M):
                    errors.append(f"assets/{name}/README.md: missing section '{heading}'")
        scan_files(asset, errors)

    for name, manifest in manifests.items():
        for ref in [*manifest.get("related", []), manifest.get("deprecated_by")]:
            if ref and ref not in manifests:
                errors.append(f"assets/{name}/manifest.yaml: references unknown asset '{ref}'")

    for error in errors:
        print(f"ERROR {error}")
    print(f"Checked {len(asset_dirs())} asset(s): {len(errors)} error(s).")
    return 1 if errors else 0


def render_catalog() -> str:
    rows = []
    for asset in asset_dirs():
        path = asset / "manifest.yaml"
        if not path.is_file():
            continue
        m = load_manifest(path)
        summary = " ".join(str(m.get("summary", "")).split()).replace("|", "\\|")
        title = str(m.get("title", asset.name)).replace("|", "\\|")
        rows.append(
            f"| [{title}](assets/{asset.name}/README.md) | `{m.get('kind', '')}` | "
            f"{m.get('maturity', '')} | {summary} |"
        )
    if not rows:
        return "_No assets have been published yet._"
    header = "| Asset | Kind | Maturity | Summary |\n|-------|------|----------|---------|"
    return header + "\n" + "\n".join(rows)


def catalog(check: bool) -> int:
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(r"(<!-- catalog:start -->\n)(.*?)(\n<!-- catalog:end -->)", re.S)
    if not pattern.search(text):
        print("ERROR README.md is missing the catalog markers")
        return 1
    updated = pattern.sub(lambda m: m.group(1) + render_catalog() + m.group(3), text)
    if check:
        if updated != text:
            print("ERROR README.md catalog is out of date; run: python tools/assets.py catalog")
            return 1
        print("Catalog is up to date.")
        return 0
    if updated != text:
        README.write_text(updated, encoding="utf-8", newline="\n")
        print("Catalog updated.")
    else:
        print("Catalog already up to date.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate every asset")
    cat = sub.add_parser("catalog", help="regenerate the README catalog")
    cat.add_argument("--check", action="store_true", help="fail if the catalog is out of date")
    args = parser.parse_args()
    return validate() if args.command == "validate" else catalog(args.check)


if __name__ == "__main__":
    sys.exit(main())
