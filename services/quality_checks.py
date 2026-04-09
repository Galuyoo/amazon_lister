from __future__ import annotations

import re
from collections import Counter
from itertools import product
from typing import Any


DISALLOWED_SYMBOL_PATTERN = re.compile(r"[★☆✓✔➡•◆►■□☑️🔥💥✨✅❌]")
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)


def build_variant_combinations(selected_variants: dict[str, list[str]]) -> list[dict[str, str]]:
    keys = list(selected_variants.keys())
    if not keys:
        return []

    value_lists = [selected_variants[k] for k in keys]
    combos: list[dict[str, str]] = []

    for values in product(*value_lists):
        combos.append(dict(zip(keys, values)))

    return combos


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def count_meaningful_words(value: str) -> int:
    words = [w for w in normalize_text(value).replace(",", " ").split(" ") if w]
    return len(words)


def contains_emoji(value: str) -> bool:
    return bool(EMOJI_PATTERN.search(value or ""))


def contains_disallowed_symbols(value: str) -> bool:
    return bool(DISALLOWED_SYMBOL_PATTERN.search(value or ""))


def starts_with_capitalized_letter(value: str) -> bool:
    stripped = (value or "").strip()
    return bool(stripped) and stripped[0].isalpha() and stripped[0].isupper()


def is_all_caps(value: str) -> bool:
    letters = [c for c in (value or "") if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def character_length(value: str) -> int:
    return len((value or "").strip())


def repeated_word_ratio(value: str) -> float:
    words = re.findall(r"\b[a-zA-Z0-9]+\b", (value or "").lower())
    if not words:
        return 0.0
    counts = Counter(words)
    return max(counts.values()) / len(words)


def build_child_sku_for_validation(
    profile: dict[str, Any],
    parent_sku: str,
    variant_values: dict[str, str],
) -> str:
    color_map = profile.get("color_sku_map", {})
    size_map = profile.get("size_code_map", {})
    design_map = profile.get("design_sku_map", {})

    def slugify_part(value: str) -> str:
        safe = value.strip().replace(" ", "-").replace("/", "-")
        while "--" in safe:
            safe = safe.replace("--", "-")
        return safe

    color_code = ""
    size_code = ""
    design_code = ""

    if "color" in variant_values:
        color_value = variant_values["color"]
        color_code = color_map.get(color_value, slugify_part(color_value))

    if "size" in variant_values:
        size_value = variant_values["size"]
        size_code = size_map.get(size_value, slugify_part(size_value))

    if "design" in variant_values:
        design_value = variant_values["design"]
        design_code = design_map.get(design_value, slugify_part(design_value))

    parts: list[str] = []

    if color_code:
        if color_code.startswith(parent_sku):
            parts.append(color_code)
        else:
            parts.append(parent_sku)
            parts.append(color_code)
    else:
        parts.append(parent_sku)

    if size_code:
        parts.append(size_code)

    if design_code:
        parts.append(design_code)

    return "-".join(parts)


def resolve_variant_image_for_validation(
    variant_values: dict[str, str],
    color_image_map: dict[str, str],
    design_color_image_url_map: dict[str, dict[str, str]] | None = None,
) -> str:
    design_color_image_url_map = design_color_image_url_map or {}

    color_value = variant_values.get("color", "")
    design_value = variant_values.get("design", "")

    if color_value and design_value:
        image_url = (
            design_color_image_url_map
            .get(color_value, {})
            .get(design_value, "")
        )
        if image_url:
            return image_url

    if color_value:
        return color_image_map.get(color_value, "")

    return ""

def validate_listing_quality(
    profile: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    score = 100
    breakdown: dict[str, int] = {
        "completeness": 40,
        "content_quality": 35,
        "variant_integrity": 15,
        "image_integrity": 10,
    }

    title = (payload.get("title") or "").strip()
    description = (payload.get("product_description") or "").strip()
    search_terms = (payload.get("generic_keywords") or "").strip()
    bullet_points = payload.get("bullet_points", [])
    selected_variants = payload.get("selected_variants", {})
    size_price_map = payload.get("size_price_map", {})
    parent_sku = (payload.get("parent_sku") or "").strip()
    variation_theme = (payload.get("variation_theme") or "").strip()
    product_category = (payload.get("product_category") or "").strip()

    parent_main_image_url = payload.get("parent_main_image_url", "")
    color_image_map = payload.get("color_image_map", {})
    design_color_image_url_map = payload.get("design_color_image_url_map", {})

    bullet_points = [str(b).strip() for b in bullet_points[:5]]
    while len(bullet_points) < 5:
        bullet_points.append("")

    # Completeness blockers
    if not title:
        blockers.append("Title is missing.")
        breakdown["completeness"] -= 10

    if not description:
        blockers.append("Product description is missing.")
        breakdown["completeness"] -= 10

    if not search_terms:
        blockers.append("Search terms are missing.")
        breakdown["completeness"] -= 10

    if len([b for b in bullet_points if b]) < 5:
        blockers.append("All five bullet points are required.")
        breakdown["completeness"] -= 10

    if variation_theme not in {"SizeColor", "Colour & Style", ""}:
        blockers.append("Variation theme is invalid.")
        breakdown["variant_integrity"] -= 5

    if product_category not in {"apparel", "accessory"}:
        blockers.append("Product category is invalid.")
        breakdown["variant_integrity"] -= 5

    # Content quality checks - title
    title_chars = character_length(title)
    if title:
        if title_chars < 80:
            warnings.append("Title looks short and may be too weak.")
            breakdown["content_quality"] -= 4
        elif title_chars < 120:
            warnings.append("Title could be expanded for better coverage.")
            breakdown["content_quality"] -= 2

        if title_chars > 200:
            warnings.append("Title looks too long and may be harder to read.")
            breakdown["content_quality"] -= 4
        elif title_chars > 150:
            warnings.append("Title is long; check readability.")
            breakdown["content_quality"] -= 2

        if contains_emoji(title) or contains_disallowed_symbols(title):
            warnings.append("Title contains emoji or decorative symbols.")
            breakdown["content_quality"] -= 4

        if repeated_word_ratio(title) > 0.30:
            warnings.append("Title appears repetitive and may be keyword-stuffed.")
            breakdown["content_quality"] -= 3

    # Content quality checks - bullets
    bullet_char_counts: list[int] = []
    normalized_bullets = [normalize_text(b) for b in bullet_points if b]

    for idx, bullet in enumerate(bullet_points, start=1):
        bullet_len = character_length(bullet)
        bullet_char_counts.append(bullet_len)

        if not bullet:
            continue

        if bullet_len < 150:
            warnings.append(f"Bullet {idx} should be at least 150 characters.")
            breakdown["content_quality"] -= 2

        if not starts_with_capitalized_letter(bullet):
            warnings.append(f"Bullet {idx} should start with a capitalized letter.")
            breakdown["content_quality"] -= 1

        if is_all_caps(bullet):
            warnings.append(f"Bullet {idx} is in all caps and may be hard to read.")
            breakdown["content_quality"] -= 1

        if contains_emoji(bullet) or contains_disallowed_symbols(bullet):
            warnings.append(f"Bullet {idx} contains emoji or decorative symbols.")
            breakdown["content_quality"] -= 1

        if count_meaningful_words(bullet) < 8:
            warnings.append(f"Bullet {idx} looks too short or low-information.")
            breakdown["content_quality"] -= 1

        if repeated_word_ratio(bullet) > 0.35:
            warnings.append(f"Bullet {idx} appears repetitive.")
            breakdown["content_quality"] -= 1

    if len(normalized_bullets) != len(set(normalized_bullets)):
        warnings.append("Some bullet points are duplicated or too similar.")
        breakdown["content_quality"] -= 4

    # Content quality checks - description
    description_chars = character_length(description)
    if description:
        if description_chars < 300:
            warnings.append("Description looks very short.")
            breakdown["content_quality"] -= 4
        elif description_chars < 1000:
            warnings.append("Description should be expanded toward 1000+ characters.")
            breakdown["content_quality"] -= 3

        if contains_emoji(description) or contains_disallowed_symbols(description):
            warnings.append("Description contains emoji or decorative symbols.")
            breakdown["content_quality"] -= 2

        if repeated_word_ratio(description) > 0.25:
            warnings.append("Description appears repetitive.")
            breakdown["content_quality"] -= 2

    # Content quality checks - search terms
    search_terms_bytes = 0
    if search_terms:
        search_terms_bytes = len(search_terms.encode("utf-8"))

        if search_terms_bytes > 249:
            blockers.append("Search terms exceed Amazon byte limit.")
            breakdown["content_quality"] -= 10
        elif search_terms_bytes < 40:
            warnings.append("Search terms look light and may be under-optimized.")
            breakdown["content_quality"] -= 4
        elif search_terms_bytes < 120:
            warnings.append("Search terms could be expanded for better coverage.")
            breakdown["content_quality"] -= 2

        if repeated_word_ratio(search_terms) > 0.30:
            warnings.append("Search terms appear repetitive.")
            breakdown["content_quality"] -= 2

    # Variant integrity
    variant_combos = build_variant_combinations(selected_variants)
    if not variant_combos:
        blockers.append("No variant combinations selected.")
        breakdown["variant_integrity"] -= 10

    child_skus = [
        build_child_sku_for_validation(profile, parent_sku or "PARENT", combo)
        for combo in variant_combos
    ]
    sku_counts = Counter(child_skus)
    duplicate_skus = [sku for sku, count in sku_counts.items() if count > 1]
    if duplicate_skus:
        blockers.append("Duplicate child SKUs detected.")
        breakdown["variant_integrity"] -= 10

    size_values = selected_variants.get("size", [])
    if size_values:
        invalid_sizes = [size for size in size_values if size_price_map.get(size, 0) <= 0]
        if invalid_sizes:
            blockers.append(f"Invalid or missing prices for sizes: {', '.join(invalid_sizes)}")
            breakdown["variant_integrity"] -= 10
    else:
        if not size_price_map or all(price <= 0 for price in size_price_map.values()):
            blockers.append("At least one valid price is required.")
            breakdown["variant_integrity"] -= 10

    # Image integrity
    if not parent_main_image_url:
        warnings.append("Parent main image is not resolved yet.")
        breakdown["image_integrity"] -= 3

    missing_variant_images: list[str] = []
    for combo in variant_combos:
        image_url = resolve_variant_image_for_validation(
            combo,
            color_image_map=color_image_map,
            design_color_image_url_map=design_color_image_url_map,
        )
        if not image_url:
            label = " / ".join([v for v in combo.values() if v])
            missing_variant_images.append(label or "Unnamed variant")

    if missing_variant_images:
        blockers.append(
            f"Missing child image URLs for {len(missing_variant_images)} variant(s)."
        )
        breakdown["image_integrity"] -= 7

    score = max(0, sum(max(0, value) for value in breakdown.values()))

    return {
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
        "breakdown": breakdown,
        "variant_count": len(variant_combos),
        "title_chars": title_chars,
        "description_chars": description_chars,
        "bullet_char_counts": bullet_char_counts,
        "search_terms_bytes": search_terms_bytes,
    }