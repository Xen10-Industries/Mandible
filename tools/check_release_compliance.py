"""Release compliance checks run by CI before packaging.

- every runtime dependency in requirements.txt is listed in THIRD_PARTY_NOTICES.txt
- LICENSE and THIRD_PARTY_NOTICES.txt exist
- the git tag (if any) matches mandible/_version.py
- no signing material or obvious secrets are tracked in git
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# requirements.txt name -> text that must appear in THIRD_PARTY_NOTICES.txt
NOTICE_NAMES = {
    "sounddevice": "sounddevice",
    "cffi": "cffi",
    "pedalboard": "pedalboard",
    "numpy": "NumPy",
    "pyside6-essentials": "PySide6-Essentials",
    "shiboken6": "shiboken6",
    "keyboard": "keyboard",
}
FORBIDDEN_SUFFIXES = (".pfx", ".p12", ".pem", ".key", ".cer", ".crt", ".snk", ".env")
SECRET_PATTERNS = re.compile(
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}"
)


def version() -> str:
    text = (ROOT / "mandible" / "_version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def main(argv: list[str]) -> int:
    errors: list[str] = []
    v = version()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", v):
        errors.append(f"version {v!r} is not semver")

    # Only tag builds are checked against the version; branch refs (manual runs) are ignored.
    ref = argv[1] if len(argv) > 1 else ""
    tag = ref[len("refs/tags/"):] if ref.startswith("refs/tags/") else ""
    if tag and tag != f"v{v}":
        errors.append(f"tag {tag!r} does not match mandible/_version.py (expected 'v{v}')")

    for name in ("LICENSE", "THIRD_PARTY_NOTICES.txt"):
        if not (ROOT / name).is_file():
            errors.append(f"{name} is missing")
    notices = (ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8") if (ROOT / "THIRD_PARTY_NOTICES.txt").is_file() else ""

    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pkg = re.split(r"[=<>!~\[ ;]", line, maxsplit=1)[0].lower()
        needle = NOTICE_NAMES.get(pkg)
        if needle is None:
            errors.append(f"{pkg}: new dependency; add it to THIRD_PARTY_NOTICES.txt and NOTICE_NAMES in this script")
        elif needle not in notices:
            errors.append(f"{pkg}: not listed in THIRD_PARTY_NOTICES.txt")

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    for rel in tracked:
        p = ROOT / rel
        if p.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"{rel}: signing material / secrets must not be committed")
        elif p.suffix.lower() in (".dll", ".exe", ".pyd"):
            errors.append(f"{rel}: prebuilt binaries must not be committed (build them in CI)")
        elif p.is_file() and p.stat().st_size < 2_000_000:
            try:
                if SECRET_PATTERNS.search(p.read_text(encoding="utf-8", errors="ignore")):
                    errors.append(f"{rel}: looks like it contains a private key or token")
            except OSError:
                pass

    for e in errors:
        print(f"::error::{e}")
    if not errors:
        print(f"Compliance checks passed for Mandible {v}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
