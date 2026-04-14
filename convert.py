#!/usr/bin/env python3
"""Convert EqualizerAPO txt exports into a small OPRA-compatible database."""

from __future__ import annotations

import json
import re
import shutil
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


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

KNOWN_PRODUCTS = [
    {
        "aliases": ["Apple AirPods Max"],
        "vendor": "Apple",
        "product": "AirPods Max",
        "subtype": "over_the_ear",
    },
    {
        "aliases": ["Hifiman Arya Organic", "HiFiMAN Arya Organic", "HIFIMAN Arya Organic"],
        "vendor": "HiFiMAN",
        "product": "Arya Organic",
        "subtype": "over_the_ear",
    },
]

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


def display_name(value: str) -> str:
    value = value.replace("_", " ").strip()
    return re.sub(r"\s+", " ", value)


def signed_words(value: str) -> str:
    value = value.strip()
    if value.startswith("-"):
        return f"minus {value[1:]}"
    if value.startswith("+"):
        return f"plus {value[1:]}"
    return value


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


def name_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def known_product_prefixes() -> list[tuple[list[str], str, str]]:
    prefixes: list[tuple[list[str], str, str]] = [
        (name_tokens(alias), product["vendor"], product["product"])
        for product in KNOWN_PRODUCTS
        for alias in product["aliases"]
    ]

    for vendor_dir in sorted(VENDORS_DIR.iterdir() if VENDORS_DIR.exists() else []):
        vendor_info = vendor_dir / "info.json"
        products_dir = vendor_dir / "products"
        if not vendor_info.exists() or not products_dir.exists():
            continue

        vendor_name = load_json(vendor_info)["name"]
        for product_dir in sorted(products_dir.iterdir()):
            product_info = product_dir / "info.json"
            if not product_info.exists():
                continue

            product_name = load_json(product_info)["name"]
            prefixes.append(
                (
                    name_tokens(f"{vendor_name} {product_name}"),
                    vendor_name,
                    product_name,
                )
            )

    return sorted(prefixes, key=lambda item: len(item[0]), reverse=True)


def known_product_subtype(vendor_name: str, product_name: str) -> str | None:
    vendor_slug = slugify(vendor_name)
    product_slug = slugify(product_name)
    for product in KNOWN_PRODUCTS:
        if slugify(product["vendor"]) == vendor_slug and slugify(product["product"]) == product_slug:
            return product["subtype"]
    return None


def parse_space_filename(path: Path) -> tuple[str, str, str, str]:
    words = path.stem.split()
    normalized = name_tokens(path.stem)

    for prefix, vendor_name, product_name in known_product_prefixes():
        if normalized[: len(prefix)] != prefix or len(words) <= len(prefix) + 1:
            continue

        return (
            vendor_name,
            product_name,
            " ".join(words[len(prefix) + 1 :]),
            words[len(prefix)],
        )

    if len(words) >= 4:
        return words[0], words[1], " ".join(words[3:]), words[2]

    require_interactive(path, "filename does not match a supported convention")
    print(
        f"\n{path.name} is not named as 'Vendor - Product - EQ Name.txt' "
        "or 'Vendor Product Source EQ Name.txt'."
    )
    return (
        prompt_text("Vendor"),
        prompt_text("Product"),
        prompt_text("EQ name", path.stem),
        prompt_text("Author/source", "Ben Merritt"),
    )


def parse_filename(path: Path) -> tuple[str, str, str, str | None]:
    parts = [part.strip() for part in path.stem.split(" - ") if part.strip()]

    if len(parts) >= 3:
        return parts[0], parts[1], " - ".join(parts[2:]), None

    words = path.stem.split()
    if len(words) >= 4:
        return parse_space_filename(path)

    require_interactive(path, "filename does not match a supported convention")
    print(
        f"\n{path.name} is not named as 'Vendor - Product - EQ Name.txt' "
        "or 'Vendor Product Source EQ Name.txt'."
    )
    return (
        prompt_text("Vendor"),
        prompt_text("Product"),
        prompt_text("EQ name", path.stem),
        prompt_text("Author/source", "Ben Merritt"),
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


def parse_hangout_product(raw_name: str) -> tuple[str, str]:
    name = display_name(raw_name)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    parts = name.split()

    if len(parts) < 2:
        raise ValueError(f"Could not infer vendor and product from selphone={raw_name!r}")

    return parts[0], " ".join(parts[1:])


def hangout_subtype(path: str) -> str:
    path_parts = {part.lower() for part in path.split("/") if part}
    if "iem" in path_parts:
        return "in_ear"
    if "earbud" in path_parts or "earbuds" in path_parts:
        return "earbuds"
    return "over_the_ear"


def hangout_rig_label(path: str) -> str:
    path_parts = [part for part in path.split("/") if part]
    if "5128" in path_parts:
        return "B&K 5128"
    for part in path_parts:
        if part.isdigit():
            return part
    return "Hangout"


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def parse_hangout_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)

    raw_product = first_query_value(query, "selphone")
    if raw_product is None:
        raise ValueError("Hangout URL is missing selphone=<product>")

    preamp = first_query_value(query, "P")
    share = first_query_value(query, "share") or ""
    share_parts = [display_name(part) for part in share.split(",") if part]
    target_name = share_parts[0] if share_parts else "Custom Target"
    source_name = share_parts[1] if len(share_parts) > 1 else display_name(raw_product)
    rig_label = hangout_rig_label(parsed.path)

    settings = [
        (key, first_query_value(query, key))
        for key in ("bass", "tilt", "treble", "ear")
        if first_query_value(query, key) is not None
    ]

    bands: list[dict[str, Any]] = []
    for index in range(1, 65):
        filter_type = first_query_value(query, f"T{index}")
        frequency = first_query_value(query, f"F{index}")
        q = first_query_value(query, f"Q{index}")
        gain = first_query_value(query, f"G{index}")

        if filter_type is None and frequency is None and q is None and gain is None:
            continue
        if filter_type is None or frequency is None or q is None or gain is None:
            raise ValueError(f"Hangout URL has incomplete filter {index}")

        frequency_value = float(frequency)
        q_value = float(q)
        gain_value = float(gain)
        if frequency_value == 0 and q_value == 0 and gain_value == 0:
            continue

        opra_type = FILTER_TYPES.get(filter_type.upper())
        if opra_type is None:
            print(f"WARNING: skipped unsupported Hangout filter type {filter_type} at T{index}")
            continue

        bands.append(
            {
                "type": opra_type,
                "frequency": number(frequency_value),
                "gain_db": number(gain_value),
                "q": number(q_value),
            }
        )

    if not bands:
        raise ValueError("Hangout URL did not contain any supported EQ bands")

    target_for_name = re.sub(r"\s+Target$", "", target_name, flags=re.I)
    setting_name = " ".join(f"{key} {signed_words(value)}" for key, value in settings)
    eq_name = " ".join(part for part in (rig_label, target_for_name, setting_name) if part)
    details = f"{rig_label} - {target_name} - {source_name}"
    if settings:
        details += " - " + " / ".join(f"{key} {value}" for key, value in settings)

    vendor_name, product_name = parse_hangout_product(raw_product)

    return {
        "vendor_name": vendor_name,
        "product_name": product_name,
        "product_subtype": hangout_subtype(parsed.path),
        "eq_name": eq_name,
        "eq_data": {
            "author": "hangout.audio",
            "details": details,
            "link": url,
            "type": "parametric_eq",
            "parameters": {
                "gain_db": number(float(preamp)) if preamp is not None else 0,
                "bands": bands,
            },
        },
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def metadata_for(
    vendor_slug: str,
    product_slug: str,
    eq_name: str,
    author: str | None = None,
) -> dict[str, Any]:
    key = (vendor_slug, product_slug, eq_name.lower())
    return KNOWN_EQ_METADATA.get(
        key,
        {
            "author": author or "Ben Merritt",
            "details": eq_name,
            "link": REPO_URL,
        },
    )


def write_eq(
    vendor_name: str,
    product_name: str,
    product_subtype: str,
    eq_name: str,
    eq_data: dict[str, Any],
) -> Path:
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
        write_json(
            product_info,
            {
                "name": product_name,
                "type": "headphones",
                "subtype": product_subtype,
            },
        )

    write_json(eq_dir / "info.json", eq_data)
    return eq_dir / "info.json"


def import_hangout_url(url: str) -> None:
    for directory in (VENDORS_DIR, DIST_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    imported = parse_hangout_url(url)
    path = write_eq(
        imported["vendor_name"],
        imported["product_name"],
        imported["product_subtype"],
        imported["eq_name"],
        imported["eq_data"],
    )
    print(f"Imported Hangout URL -> {path.relative_to(ROOT)}")


def convert_inbox() -> None:
    for directory in (INBOX_DIR, PROCESSED_DIR, VENDORS_DIR, DIST_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    for source in sorted(INBOX_DIR.glob("*.txt")):
        vendor_name, product_name, eq_name, author = parse_filename(source)
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
            subtype = known_product_subtype(vendor_name, product_name)
            if subtype is None:
                require_interactive(source, f"{vendor_name} - {product_name} is a new product")
                subtype = prompt_subtype(product_name)
            write_json(
                product_info,
                {
                    "name": product_name,
                    "type": "headphones",
                    "subtype": subtype,
                },
            )

        eq_data = metadata_for(vendor_slug, product_slug, eq_name, author)
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
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hangout-url",
        action="append",
        default=[],
        help="Import a shared graph.hangout.audio EQ URL directly into the OPRA database.",
    )
    args = parser.parse_args()

    if args.hangout_url:
        for url in args.hangout_url:
            import_hangout_url(url)
    else:
        convert_inbox()

    build_dist()


if __name__ == "__main__":
    main()
