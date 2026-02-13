#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def normalize_forbidden_lib_name(value: str) -> str:
    token = value.strip()
    if not token:
        raise ValueError("Forbidden library name cannot be empty")

    if token.endswith(".so"):
        return token if token.startswith("lib") else f"lib{token}"

    return f"{token}.so" if token.startswith("lib") else f"lib{token}.so"


def collect_apk_layout(apk_path: Path) -> tuple[list[str], list[str], set[str]]:
    with zipfile.ZipFile(apk_path) as zf:
        names = zf.namelist()

    root_dex_entries = sorted(
        name
        for name in names
        if "/" not in name and name.startswith("classes") and name.endswith(".dex")
    )
    shared_lib_basenames = {
        Path(name).name for name in names if name.startswith("lib/") and name.endswith(".so")
    }

    return names, root_dex_entries, shared_lib_basenames


def validate_hardened_apk(
    apk_path: Path,
    required_entries: list[str],
    forbidden_libs: list[str],
    min_plaintext_dex: int | None,
    max_plaintext_dex: int | None,
) -> list[str]:
    names, root_dex_entries, shared_lib_basenames = collect_apk_layout(apk_path)
    errors: list[str] = []

    for entry in required_entries:
        if entry not in names:
            errors.append(f"Missing required entry: {entry}")

    for forbidden in forbidden_libs:
        normalized = normalize_forbidden_lib_name(forbidden)
        if normalized in shared_lib_basenames:
            errors.append(f"Forbidden native library remains in APK: {normalized}")

    dex_count = len(root_dex_entries)
    if min_plaintext_dex is not None and dex_count < min_plaintext_dex:
        errors.append(
            f"Plaintext classes*.dex count too small: {dex_count} < {min_plaintext_dex} (found: {root_dex_entries})"
        )
    if max_plaintext_dex is not None and dex_count > max_plaintext_dex:
        errors.append(
            f"Plaintext classes*.dex count too large: {dex_count} > {max_plaintext_dex} (found: {root_dex_entries})"
        )

    return errors


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate hardened APK layout invariants, such as required payload entries, "
            "forbidden plaintext native libs, and plaintext dex count limits."
        )
    )
    parser.add_argument("--apk", required=True, help="Path to hardened APK")
    parser.add_argument(
        "--require-entry",
        action="append",
        default=[],
        help="APK entry that must exist (repeatable), e.g. assets/kapp_payload.bin",
    )
    parser.add_argument(
        "--forbid-lib",
        action="append",
        default=[],
        help="Library basename to forbid (repeatable), e.g. mmkv or libmmkv.so",
    )
    parser.add_argument(
        "--min-plaintext-dex",
        type=int,
        default=None,
        help="Minimum allowed count of root classes*.dex entries",
    )
    parser.add_argument(
        "--max-plaintext-dex",
        type=int,
        default=None,
        help="Maximum allowed count of root classes*.dex entries",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    apk_path = Path(args.apk)
    if not apk_path.exists():
        parser.error(f"APK does not exist: {apk_path}")

    if args.min_plaintext_dex is not None and args.min_plaintext_dex < 0:
        parser.error("--min-plaintext-dex must be >= 0")
    if args.max_plaintext_dex is not None and args.max_plaintext_dex < 0:
        parser.error("--max-plaintext-dex must be >= 0")
    if (
        args.min_plaintext_dex is not None
        and args.max_plaintext_dex is not None
        and args.min_plaintext_dex > args.max_plaintext_dex
    ):
        parser.error("--min-plaintext-dex cannot be greater than --max-plaintext-dex")

    errors = validate_hardened_apk(
        apk_path=apk_path,
        required_entries=args.require_entry,
        forbidden_libs=args.forbid_lib,
        min_plaintext_dex=args.min_plaintext_dex,
        max_plaintext_dex=args.max_plaintext_dex,
    )
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    print(f"[OK] Hardened APK layout check passed: {apk_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
