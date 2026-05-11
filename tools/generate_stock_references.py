from __future__ import annotations

import argparse
import csv
import json
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXISTING_CONFIG = REPO_ROOT / "config" / "stock_references.json"
DEFAULT_OUTPUT_CONFIG = REPO_ROOT / "config" / "stock_references.generated.json"

UNEEK_REQUIRED_COLUMNS = ["ItemNo", "ProductCode", "ColourDesc", "SizeDesc"]
UNEEK_SIZE_ALIASES = {
    "Small": "S",
    "Medium": "M",
    "Large": "L",
    "X Large": "XL",
    "XL": "XL",
    "XX Large": "2XL",
    "2XL": "2XL",
    "XXX Large": "3XL",
    "XXXL Large": "3XL",
    "3XL": "3XL",
    "XXXX Large": "4XL",
    "XXXXL Large": "4XL",
    "4XL": "4XL",
    "XS": "XS",
    "X Small": "XS",
    "Xtra Small": "XS",
}


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def load_references(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as json_file:
        data = json.load(json_file)

    references = data.get("references", data)
    return references if isinstance(references, dict) else {}


def validate_required_columns(headers: list[str], required: list[str], label: str) -> list[str]:
    missing = [column for column in required if column not in headers]
    if not missing:
        return []
    return [f"{label}: missing required column(s): {', '.join(missing)}"]


def normalize_uneek_size_label(size_desc: str) -> tuple[str, bool]:
    size_desc = str(size_desc or "").strip()
    if size_desc in UNEEK_SIZE_ALIASES:
        return UNEEK_SIZE_ALIASES[size_desc], UNEEK_SIZE_ALIASES[size_desc] != size_desc
    return size_desc, False


def generate_uneek_references(csv_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rows, headers = read_csv_rows(csv_path)
    errors = validate_required_columns(headers, UNEEK_REQUIRED_COLUMNS, "Uneek")
    if errors:
        return {}, {
            "source": str(csv_path),
            "errors": errors,
            "warnings": [],
            "row_counts": {},
            "duplicate_keys": [],
            "missing_item_no_rows": [],
            "empty_product_code_rows": [],
            "size_labels_normalized_count": 0,
            "unknown_size_desc_values": [],
        }

    row_counts: dict[str, int] = defaultdict(int)
    mapped_counts: dict[str, int] = defaultdict(int)
    duplicate_keys: list[dict[str, Any]] = []
    missing_item_no_rows: list[dict[str, Any]] = []
    empty_product_code_rows: list[dict[str, Any]] = []
    unknown_size_desc: dict[str, dict[str, Any]] = OrderedDict()
    size_labels_normalized_count = 0
    product_maps: dict[str, OrderedDict[str, str]] = OrderedDict()
    seen_keys: dict[tuple[str, str], dict[str, Any]] = {}

    for row_number, row in enumerate(rows, start=2):
        item_no = str(row.get("ItemNo", "") or "").strip()
        product_code = str(row.get("ProductCode", "") or "").strip()
        colour_desc = str(row.get("ColourDesc", "") or "").strip()
        size_desc = str(row.get("SizeDesc", "") or "").strip()
        size_label, size_was_normalized = normalize_uneek_size_label(size_desc)
        if size_was_normalized:
            size_labels_normalized_count += 1
        elif size_desc and size_desc not in UNEEK_SIZE_ALIASES:
            unknown_entry = unknown_size_desc.setdefault(size_desc, {"count": 0, "sample_rows": []})
            unknown_entry["count"] += 1
            if len(unknown_entry["sample_rows"]) < 10:
                unknown_entry["sample_rows"].append(row_number)

        if not product_code:
            empty_product_code_rows.append({
                "row": row_number,
                "item_no": item_no,
                "colour": colour_desc,
                "size": size_desc,
                "size_label": size_label,
            })
            continue

        row_counts[product_code] += 1

        if not item_no:
            missing_item_no_rows.append({
                "row": row_number,
                "product_code": product_code,
                "colour": colour_desc,
                "size": size_desc,
                "size_label": size_label,
            })
            continue

        variant_key = f"{colour_desc}|{size_label}"
        seen_key = (product_code, variant_key)
        previous = seen_keys.get(seen_key)
        if previous:
            duplicate_keys.append({
                "product_code": product_code,
                "variant_key": variant_key,
                "original_size": size_desc,
                "first_row": previous["row"],
                "first_item_no": previous["item_no"],
                "first_original_size": previous["original_size"],
                "duplicate_row": row_number,
                "duplicate_item_no": item_no,
            })
            continue

        seen_keys[seen_key] = {
            "row": row_number,
            "item_no": item_no,
            "original_size": size_desc,
        }
        product_maps.setdefault(product_code, OrderedDict())[variant_key] = item_no
        mapped_counts[product_code] += 1

    references: dict[str, Any] = OrderedDict()
    for product_code, variant_map in product_maps.items():
        references[product_code] = {
            "supplier": "uneek",
            "strict_stock_ready": True,
            "variant_key_fields": ["color", "size"],
            "variant_stock_key_map": variant_map,
        }

    report = {
        "source": str(csv_path),
        "errors": [],
        "warnings": [],
        "row_counts": {
            product_code: {
                "source_rows": row_counts[product_code],
                "mapped_variants": mapped_counts.get(product_code, 0),
            }
            for product_code in sorted(row_counts)
        },
        "duplicate_keys": duplicate_keys,
        "missing_item_no_rows": missing_item_no_rows,
        "empty_product_code_rows": empty_product_code_rows,
        "size_labels_normalized_count": size_labels_normalized_count,
        "unknown_size_desc_values": [
            {
                "size_desc": size_desc,
                "count": details["count"],
                "sample_rows": details["sample_rows"],
            }
            for size_desc, details in unknown_size_desc.items()
        ],
    }

    return references, report


def analyze_ralawise_csv(csv_path: Path) -> dict[str, Any]:
    rows, headers = read_csv_rows(csv_path)
    header_set = set(headers)
    basic_stock_columns = {"SKU", "free", "DiscontinuedStatus"}
    has_only_stock_columns = bool(header_set) and header_set.issubset(basic_stock_columns)

    report = {
        "source": str(csv_path),
        "rows": len(rows),
        "headers": headers,
        "generated_references": 0,
        "warnings": [],
    }

    if has_only_stock_columns:
        report["warnings"].append(
            "Ralawise file only has SKU/free/DiscontinuedStatus stock columns. "
            "No colour/size mapping can be generated safely; use a product catalogue or explicit mapping file."
        )
        return report

    report["warnings"].append(
        "Ralawise stock reference generation is not implemented for this file shape. "
        "Provide catalogue fields that map each SKU to product, colour, and size before generating references."
    )
    return report


def compare_reference_maps(
    generated: dict[str, Any],
    existing: dict[str, Any],
    reference_key: str,
) -> dict[str, Any]:
    generated_ref = generated.get(reference_key, {})
    existing_ref = existing.get(reference_key, {})
    generated_map = generated_ref.get("variant_stock_key_map", {}) if isinstance(generated_ref, dict) else {}
    existing_map = existing_ref.get("variant_stock_key_map", {}) if isinstance(existing_ref, dict) else {}

    if not generated_ref:
        return {"reference_key": reference_key, "status": "generated reference missing"}
    if not existing_ref:
        return {"reference_key": reference_key, "status": "existing reference missing"}

    generated_keys = set(generated_map)
    existing_keys = set(existing_map)
    added_keys = sorted(generated_keys - existing_keys)
    removed_keys = sorted(existing_keys - generated_keys)
    changed_values = sorted(
        {
            key: {
                "generated": generated_map.get(key),
                "existing": existing_map.get(key),
            }
            for key in generated_keys & existing_keys
            if generated_map.get(key) != existing_map.get(key)
        }.items()
    )

    return {
        "reference_key": reference_key,
        "status": "different" if added_keys or removed_keys or changed_values else "same",
        "generated_variant_count": len(generated_map),
        "existing_variant_count": len(existing_map),
        "added_key_count": len(added_keys),
        "removed_key_count": len(removed_keys),
        "changed_value_count": len(changed_values),
        "added_keys_sample": added_keys[:20],
        "removed_keys_sample": removed_keys[:20],
        "changed_values_sample": [
            {"variant_key": key, **value}
            for key, value in changed_values[:20]
        ],
    }


def write_generated_references(path: Path, references: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"references": references}
    with path.open("w", encoding="utf-8", newline="\n") as json_file:
        json.dump(payload, json_file, indent=2, ensure_ascii=False)
        json_file.write("\n")


def print_section(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def print_uneek_report(report: dict[str, Any]) -> None:
    print_section("Uneek report")
    print(f"Source: {report.get('source', '')}")

    for error in report.get("errors", []):
        print(f"ERROR: {error}")

    row_counts = report.get("row_counts", {})
    print(f"Garments found: {len(row_counts)}")
    for product_code, counts in list(row_counts.items())[:30]:
        print(
            f"- {product_code}: "
            f"{counts.get('source_rows', 0)} row(s), "
            f"{counts.get('mapped_variants', 0)} mapped variant(s)"
        )
    if len(row_counts) > 30:
        print(f"- ... {len(row_counts) - 30} more garment(s)")

    duplicate_keys = report.get("duplicate_keys", [])
    missing_item_no_rows = report.get("missing_item_no_rows", [])
    empty_product_code_rows = report.get("empty_product_code_rows", [])
    unknown_size_desc_values = report.get("unknown_size_desc_values", [])

    print(f"Size labels normalized: {report.get('size_labels_normalized_count', 0)}")
    print(f"Unknown SizeDesc values: {len(unknown_size_desc_values)}")
    for item in unknown_size_desc_values[:20]:
        print(
            f"- {item['size_desc']}: "
            f"{item['count']} row(s), sample rows {item['sample_rows']}"
        )

    print(f"Duplicate keys after normalization: {len(duplicate_keys)}")
    for item in duplicate_keys[:20]:
        print(
            f"- {item['product_code']} {item['variant_key']}: "
            f"row {item['first_row']}={item['first_item_no']} ({item['first_original_size']}), "
            f"row {item['duplicate_row']}={item['duplicate_item_no']} ({item['original_size']})"
        )

    print(f"Rows with missing ItemNo: {len(missing_item_no_rows)}")
    for item in missing_item_no_rows[:20]:
        print(f"- row {item['row']}: {item['product_code']} {item['colour']}|{item['size']}")

    print(f"Rows with empty ProductCode: {len(empty_product_code_rows)}")
    for item in empty_product_code_rows[:20]:
        print(f"- row {item['row']}: ItemNo={item['item_no']} {item['colour']}|{item['size']}")


def print_ralawise_report(report: dict[str, Any]) -> None:
    print_section("Ralawise report")
    print(f"Source: {report.get('source', '')}")
    print(f"Rows: {report.get('rows', 0)}")
    print(f"Headers: {', '.join(report.get('headers', []))}")
    for warning in report.get("warnings", []):
        print(f"WARNING: {warning}")


def print_comparison_report(report: dict[str, Any]) -> None:
    print_section(f"Existing config comparison: {report.get('reference_key', '')}")
    print(f"Status: {report.get('status', '')}")
    if report.get("status") not in {"same", "different"}:
        return

    print(f"Generated variants: {report.get('generated_variant_count', 0)}")
    print(f"Existing variants: {report.get('existing_variant_count', 0)}")
    print(f"Added keys: {report.get('added_key_count', 0)}")
    for key in report.get("added_keys_sample", []):
        print(f"- added: {key}")
    print(f"Removed keys: {report.get('removed_key_count', 0)}")
    for key in report.get("removed_keys_sample", []):
        print(f"- removed: {key}")
    print(f"Changed values: {report.get('changed_value_count', 0)}")
    for item in report.get("changed_values_sample", []):
        print(
            f"- changed: {item['variant_key']} "
            f"generated={item['generated']} existing={item['existing']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate draft Amazon Lister stock reference JSON from supplier files.",
    )
    parser.add_argument("--uneek-csv", type=Path, help="Path to Uneek stock_levels.csv")
    parser.add_argument("--ralawise-csv", type=Path, help="Path to Ralawise Stock_Update CSV")
    parser.add_argument(
        "--existing-config",
        type=Path,
        default=DEFAULT_EXISTING_CONFIG,
        help=f"Existing stock_references.json to compare against. Default: {DEFAULT_EXISTING_CONFIG}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_CONFIG,
        help=f"Draft output path. Default: {DEFAULT_OUTPUT_CONFIG}",
    )
    parser.add_argument(
        "--compare-key",
        default="UC106",
        help="Reference key to compare against the existing config. Default: UC106",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    generated_references: dict[str, Any] = OrderedDict()

    if args.uneek_csv:
        uneek_references, uneek_report = generate_uneek_references(args.uneek_csv)
        generated_references.update(uneek_references)
        print_uneek_report(uneek_report)
    else:
        print_section("Uneek report")
        print("No Uneek CSV provided.")

    if args.ralawise_csv:
        ralawise_report = analyze_ralawise_csv(args.ralawise_csv)
        print_ralawise_report(ralawise_report)

    if generated_references:
        write_generated_references(args.output, generated_references)
        print_section("Generated output")
        print(f"Wrote draft references to: {args.output}")
        print("Did not overwrite config/stock_references.json.")
    else:
        print_section("Generated output")
        print("No references were generated.")

    existing_references = load_references(args.existing_config)
    if generated_references and existing_references:
        comparison = compare_reference_maps(
            generated=generated_references,
            existing=existing_references,
            reference_key=args.compare_key,
        )
        print_comparison_report(comparison)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
