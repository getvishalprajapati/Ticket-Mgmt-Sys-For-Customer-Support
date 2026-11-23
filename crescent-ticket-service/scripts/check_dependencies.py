"""Verify the dependency policy for this project.

Checks
  1. every Python requirement is pinned with == (requirements.txt, requirements-dev.txt)
  2. every npm package is pinned exactly (database/package.json, database/package-lock.json)
  3. the active Python environment contains exactly the pinned packages (no silent extras)
  4. (online) each pinned version was published on or before the cutoff date
       - PyPI:  https://pypi.org/pypi/<name>/<version>/json  (earliest file upload time)
       - npm:   https://registry.npmjs.org/<name>             (time[<version>], dist.integrity)
  5. (online) no known vulnerabilities for the pinned versions
       - OSV:   https://api.osv.dev/v1/querybatch

Usage (from the project root, with the virtual environment active):
  python scripts/check_dependencies.py              # all checks (needs internet access)
  python scripts/check_dependencies.py --offline    # checks 1-3 only
  python scripts/check_dependencies.py --markdown   # also print a Markdown report table

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 9, 25, 23, 59, 59, tzinfo=UTC)
USER_AGENT = "crescent-ticket-service-dependency-check/1.0"
# Installer tooling present in every virtual environment; documented separately.
TOOLING = {"pip", "setuptools", "wheel"}

# Vulnerabilities reviewed and explicitly accepted (see docs/dependencies.md,
# "Known vulnerability"). Anything not listed here fails the check.
ACCEPTED_VULNERABILITIES = {
    ("PyPI", "certifi", "2026.7.22"): {
        "ids": {"GHSA-6q48-6c7w-9gw2", "PYSEC-2026-4320"},
        "reason": (
            "fixed only in certifi 2026.10.18+ (published after the 2026-09-25 cutoff); certifi is a "
            "dev/test-only dependency of httpx and the test client makes no outbound TLS connections"
        ),
    },
}
REQUIREMENT_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;#]+)\s*(?:;(?P<marker>[^#]+))?")


@dataclass
class Package:
    ecosystem: str  # "PyPI" or "npm"
    name: str
    version: str
    source_file: str
    marker: str | None = None
    integrity: str | None = None  # npm lockfile hash
    published: datetime | None = None
    source_url: str = ""
    vulnerabilities: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


# --- parsing -------------------------------------------------------------------------------


def read_requirements(path: Path, seen: set[Path] | None = None) -> tuple[list[Package], list[str]]:
    seen = seen or set()
    if path in seen:
        return [], []
    seen.add(path)
    packages: list[Package] = []
    errors: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            nested, nested_errors = read_requirements(path.parent / line[3:].strip(), seen)
            packages += nested
            errors += nested_errors
            continue
        match = REQUIREMENT_LINE.match(line)
        if not match:
            errors.append(f"{path.name}:{number}: not pinned with '==': {raw.strip()}")
            continue
        marker = match.group("marker").strip() if match.group("marker") else None
        packages.append(Package("PyPI", match.group("name"), match.group("version"), path.name, marker))
    return packages, errors


def read_npm_lock() -> tuple[list[Package], list[str]]:
    errors: list[str] = []
    manifest = json.loads((ROOT / "database" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "database" / "package-lock.json").read_text(encoding="utf-8"))
    for name, spec in manifest.get("dependencies", {}).items():
        if not re.fullmatch(r"\d+\.\d+\.\d+", spec):
            errors.append(f"package.json: {name} is not pinned to an exact version ({spec})")
        locked = lock["packages"].get(f"node_modules/{name}", {}).get("version")
        if locked != spec:
            errors.append(f"package-lock.json: {name} locked at {locked}, package.json requires {spec}")
    packages = []
    for key, entry in lock["packages"].items():
        if not key:
            continue
        name = key.split("node_modules/")[-1]
        if not entry.get("integrity") or not entry.get("resolved", "").startswith("https://registry.npmjs.org/"):
            errors.append(f"package-lock.json: {name} has no registry tarball/integrity")
        packages.append(
            Package("npm", name, entry["version"], "database/package-lock.json", integrity=entry.get("integrity"))
        )
    return packages, errors


def applies(pkg: Package) -> bool:
    return pkg.marker is None or Marker(pkg.marker).evaluate()


# --- checks --------------------------------------------------------------------------------


def check_installed(packages: list[Package]) -> list[str]:
    """The running environment must contain exactly the pinned packages."""
    errors = []
    pinned = {canonicalize_name(p.name): p.version for p in packages if applies(p)}
    installed = {canonicalize_name(d.metadata["Name"]): d.version for d in metadata.distributions()}
    for name, version in sorted(pinned.items()):
        if name not in installed:
            errors.append(f"installed environment: {name}=={version} is pinned but not installed")
        elif installed[name] != version:
            errors.append(f"installed environment: {name} is {installed[name]}, pinned {version}")
    for name, version in sorted(installed.items()):
        if name not in pinned and name not in TOOLING:
            errors.append(f"installed environment: {name}=={version} is installed but not pinned")
    return errors


def _get_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_publication_dates(packages: list[Package]) -> None:
    npm_cache: dict[str, dict] = {}
    for pkg in packages:
        try:
            if pkg.ecosystem == "PyPI":
                pkg.source_url = f"https://pypi.org/pypi/{pkg.name}/{pkg.version}/json"
                files = _get_json(pkg.source_url)["urls"]
                if not files:
                    pkg.problems.append("no files published for this version")
                    continue
                pkg.published = min(datetime.fromisoformat(f["upload_time_iso_8601"]) for f in files)
                if all(f.get("yanked") for f in files):
                    pkg.problems.append("version is yanked")
            else:
                pkg.source_url = "https://registry.npmjs.org/" + pkg.name.replace("/", "%2f")
                doc = npm_cache.setdefault(pkg.name, _get_json(pkg.source_url))
                pkg.published = datetime.fromisoformat(doc["time"][pkg.version])
                registry_integrity = doc["versions"][pkg.version]["dist"].get("integrity")
                if registry_integrity != pkg.integrity:
                    pkg.problems.append("package-lock integrity does not match the registry")
                if doc["versions"][pkg.version].get("deprecated"):
                    pkg.problems.append("version is deprecated on npm")
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            pkg.problems.append(f"could not verify publication date: {exc}")
            continue
        if pkg.published and pkg.published > CUTOFF:
            pkg.problems.append(f"published {pkg.published:%Y-%m-%d}, after the cutoff {CUTOFF:%Y-%m-%d}")


def fetch_vulnerabilities(packages: list[Package]) -> tuple[list[str], list[str]]:
    """Return (errors, accepted-risk warnings)."""
    queries = [{"package": {"name": p.name, "ecosystem": p.ecosystem}, "version": p.version} for p in packages]
    try:
        results = _get_json("https://api.osv.dev/v1/querybatch", {"queries": queries})["results"]
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        return [f"OSV vulnerability lookup failed: {exc}"], []
    warnings = []
    for pkg, result in zip(packages, results, strict=True):
        pkg.vulnerabilities = sorted(v["id"] for v in result.get("vulns", []))
        accepted = ACCEPTED_VULNERABILITIES.get((pkg.ecosystem, pkg.name, pkg.version), {"ids": set(), "reason": ""})
        unreviewed = [v for v in pkg.vulnerabilities if v not in accepted["ids"]]
        if unreviewed:
            pkg.problems.append("known vulnerabilities: " + ", ".join(unreviewed))
        reviewed = [v for v in pkg.vulnerabilities if v in accepted["ids"]]
        if reviewed:
            warnings.append(f"{pkg.ecosystem} {pkg.name}=={pkg.version}: ACCEPTED {', '.join(reviewed)} - {accepted['reason']}")
    return [], warnings


def node_version() -> str:
    try:
        return subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "not found"


# --- report --------------------------------------------------------------------------------


def markdown_table(packages: list[Package]) -> str:
    lines = [
        "| Ecosystem | Package | Version | Published (UTC) | Listed in | Known vulnerabilities (OSV) | Verification source |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in packages:
        published = f"{p.published:%Y-%m-%d %H:%M}" if p.published else "unverified"
        where = p.source_file + (f" (`{p.marker.strip()}`)" if p.marker else "")
        vulns = ", ".join(p.vulnerabilities) if p.vulnerabilities else "none"
        lines.append(f"| {p.ecosystem} | {p.name} | {p.version} | {published} | {where} | {vulns} | {p.source_url} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip registry and vulnerability lookups")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table of all packages")
    parser.add_argument("--skip-installed", action="store_true", help="do not compare with the active environment")
    args = parser.parse_args()

    python_packages, errors = read_requirements(ROOT / "requirements-dev.txt")
    npm_packages, npm_errors = read_npm_lock()
    errors += npm_errors
    if not args.skip_installed:
        errors += check_installed(python_packages)

    all_packages = python_packages + npm_packages
    warnings: list[str] = []
    if not args.offline:
        fetch_publication_dates(all_packages)
        vulnerability_errors, warnings = fetch_vulnerabilities(all_packages)
        errors += vulnerability_errors
    for pkg in all_packages:
        errors += [f"{pkg.ecosystem} {pkg.name}=={pkg.version}: {problem}" for problem in pkg.problems]

    print(f"Python {sys.version.split()[0]}, Node.js {node_version()}, cutoff {CUTOFF:%Y-%m-%d}")
    print(f"Checked {len(python_packages)} Python and {len(npm_packages)} npm packages"
          + (" (offline: pins and environment only)" if args.offline else ""))
    if args.markdown:
        print()
        print(markdown_table(all_packages))
        print()
    for warning in warnings:
        print(f"WARNING {warning}")
    if errors:
        print(f"\nFAILED - {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("OK - all dependency checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
