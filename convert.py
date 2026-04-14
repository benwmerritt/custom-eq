#!/usr/bin/env python3
"""Convert EqualizerAPO txt exports into a small OPRA-compatible database."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
INBOX_DIR = ROOT / "inbox"
PROCESSED_DIR = ROOT / "processed"
DATABASE_DIR = ROOT / "database"
VENDORS_DIR = DATABASE_DIR / "vendors"
DIST_DIR = ROOT / "dist"
DIST_FILE = DIST_DIR / "database_v1.jsonl"
REPO_URL = "https://github.com/benwmerritt/custom-eq"

FILTER_TYPES = {
    "PK": "peak_dip",
    "LS": "low_shelf",
    "LSC": "low_shelf",
    "HS": "high_shelf",
    "HSC": "high_shelf",
}

PRODUCT_SUBTYPES = {"over_the_ear", "on_ear", "in_ear", "earbuds"}

KNOWN_EQ_METADATA = {
    ("hisenior", "mega7", "5128 df"): {
        "author": "hangout.audio",
        "details": (
            "B&K 5128 - Diffuse-Field target - Mega7 Balance - "
            "tilt bass +8 / treble -4"
        ),
        "link": (
            "https://graph.hangout.audio/iem/5128/"
            "?share=Diffuse_Field_Target,Mega7_Balance&bass=8&tilt=0&treble=-4&ear=0"
        ),
    },
    ("hisenior", "mega7", "ief pref 2025"): {
        "author": "hangout.audio",
        "details": "IEF Preference 2025 target - Mega7 Balance",
    },
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "custom"


def require_interactive(path: Path, reason: str) -> None:
    if not sys.stdin.isatty():
        raise ValueError(
            f"{path.name}: {reason}. Rename it as 'Vendor - Product - EQ Name.txt' "
            "or run convert.py in an interactive terminal."
        )


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print(f"{label} is required.")


def prompt_subtype(product_name: str) -> str:
    options = ", ".join(sorted(PRODUCT_SUBTYPES))
    while True:
        subtype = input(f"Subtype for {product_name} ({options}): ").strip()
        if subtype in PRODUCT_SUBTYPES:
            return subtype
        print(f"Subtype must be one of: {options}")


def parse_filename(path: Path) -> tuple[str, str, str]:
    parts = [part.strip() for part in path.stem.split(" - ") if part.strip()]

    if len(parts) >= 3:
        return parts[0], parts[1], " - ".join(parts[2:])

    require_interactive(path, "filename does not match the expected convention")
    print(f"\n{path.name} is not named as 'Vendor - Product - EQ Name.txt'.")
    return (
        prompt_text("Vendor"),
        prompt_text("Product"),
        prompt_text("EQ name", path.stem),
    )


def number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def parse_eq_file(path: Path) -> dict[str, Any]:
    preamp = 0.0
    bands: list[dict[str, Any]] = []

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        preamp_match = re.match(r"^Preamp:\s*([-+]?\d+(?:\.\d+)?)\s*dB$", line, re.I)
        if preamp_match:
            preamp = float(preamp_match.group(1))
            continue

        filter_match = re.match(
            r"^Filter\s+\d+:\s+"
            r"(?P<state>ON|OFF)\s+"
            r"(?P<type>[A-Z]+)\s+"
            r"Fc\s+(?P<frequency>[-+]?\d+(?:\.\d+)?)\s+Hz\s+"
            r"Gain\s+(?P<gain>[-+]?\d+(?:\.\d+)?)\s+dB\s+"
            r"Q\s+(?P<q>[-+]?\d+(?:\.\d+)?)$",
            line,
            re.I,
        )
        if not filter_match:
            print(f"WARNING: skipped unrecognized line in {path.name}: {line}")
            continue

        if filter_match.group("state").upper() != "ON":
            continue

        apo_type = filter_match.group("type").upper()
        opra_type = FILTER_TYPES.get(apo_type)
        if opra_type is None:
            print(f"WARNING: skipped unsupported filter type {apo_type} in {path.name}")
            continue

        bands.append(
            {
                "type": opra_type,
                "frequency": number(float(filter_match.group("frequency"))),
                "gain_db": number(float(filter_match.group("gain"))),
                "q": number(float(filter_match.group("q"))),
            }
        )

    if not bands:
        raise ValueError(f"{path} did not contain any supported active EQ bands")

    return {"gain_db": number(preamp), "bands": bands}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def metadata_for(vendor_slug: str, product_slug: str, eq_name: str) -> dict[str, Any]:
    key = (vendor_slug, product_slug, eq_name.lower())
    return KNOWN_EQ_METADATA.get(
        key,
        {
            "author": "Ben Merritt",
            "details": eq_name,
            "link": REPO_URL,
        },
    )


def convert_inbox() -> None:
    for directory in (INBOX_DIR, PROCESSED_DIR, VENDORS_DIR, DIST_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    for source in sorted(INBOX_DIR.glob("*.txt")):
        vendor_name, product_name, eq_name = parse_filename(source)
        vendor_slug = slugify(vendor_name)
        product_slug = slugify(product_name)
        eq_slug = slugify(eq_name)

        vendor_dir = VENDORS_DIR / vendor_slug
        product_dir = vendor_dir / "products" / product_slug
        eq_dir = product_dir / "eq" / eq_slug

        vendor_info = vendor_dir / "info.json"
        if not vendor_info.exists():
            write_json(vendor_info, {"name": vendor_name})

        product_info = product_dir / "info.json"
        if not product_info.exists():
            require_interactive(source, f"{vendor_name} - {product_name} is a new product")
            write_json(
                product_info,
                {
                    "name": product_name,
                    "type": "headphones",
                    "subtype": prompt_subtype(product_name),
                },
            )

        eq_data = metadata_for(vendor_slug, product_slug, eq_name)
        eq_data = {
            **eq_data,
            "type": "parametric_eq",
            "parameters": parse_eq_file(source),
        }
        write_json(eq_dir / "info.json", eq_data)

        destination = PROCESSED_DIR / source.name
        if destination.exists():
            destination.unlink()
        shutil.move(str(source), destination)
        print(f"Converted {source.relative_to(ROOT)} -> {eq_dir.relative_to(ROOT) / 'info.json'}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_dist() -> None:
    entries: list[dict[str, Any]] = []
    vendor_ids: set[str] = set()
    product_ids: set[str] = set()

    for vendor_dir in sorted(VENDORS_DIR.iterdir() if VENDORS_DIR.exists() else []):
        if not vendor_dir.is_dir():
            continue

        vendor_id = vendor_dir.name
        vendor_info = vendor_dir / "info.json"
        if not vendor_info.exists():
            continue

        vendor_ids.add(vendor_id)
        entries.append({"type": "vendor", "id": vendor_id, "data": load_json(vendor_info)})

        products_dir = vendor_dir / "products"
        for product_dir in sorted(products_dir.iterdir() if products_dir.exists() else []):
            if not product_dir.is_dir():
                continue

            product_id = f"{vendor_id}::{product_dir.name}"
            product_info = product_dir / "info.json"
            if not product_info.exists():
                continue

            product_data = load_json(product_info)
            product_data["vendor_id"] = vendor_id
            product_ids.add(product_id)
            entries.append({"type": "product", "id": product_id, "data": product_data})

            eq_parent = product_dir / "eq"
            for eq_dir in sorted(eq_parent.iterdir() if eq_parent.exists() else []):
                if not eq_dir.is_dir():
                    continue

                eq_info = eq_dir / "info.json"
                if not eq_info.exists():
                    continue

                eq_id = f"{vendor_id}:{product_dir.name}::{eq_dir.name}"
                eq_data = load_json(eq_info)
                eq_data["product_id"] = product_id
                entries.append({"type": "eq", "id": eq_id, "data": eq_data})

    for entry in entries:
        if entry["type"] == "product" and entry["data"]["vendor_id"] not in vendor_ids:
            raise ValueError(f"Product {entry['id']} references missing vendor")
        if entry["type"] == "eq" and entry["data"]["product_id"] not in product_ids:
            raise ValueError(f"EQ {entry['id']} references missing product")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    DIST_FILE.write_text(
        "".join(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )
    print(f"Wrote {DIST_FILE.relative_to(ROOT)} with {len(entries)} entries")


def main() -> None:
    convert_inbox()
    build_dist()


if __name__ == "__main__":
    main()
