from services.sku_replacement import (
    apply_sku_component_replace_rules,
    apply_sku_replace_rules,
    build_sku_replacement_fingerprint,
    parse_sku_replace_rules,
)


def test_parses_plain_and_quoted_replacement_rules() -> None:
    result = parse_sku_replace_rules('MPNLONG=>MPNSHORT\n"PRINT-"=>"DEF-"')

    assert result == {
        "valid": True,
        "rules": [
            {"source": "MPNLONG", "replacement": "MPNSHORT"},
            {"source": "PRINT-", "replacement": "DEF-"},
        ],
        "errors": [],
    }


def test_replacements_are_literal_case_insensitive_and_ordered() -> None:
    rules = parse_sku_replace_rules("print-=>DEF-\nLONG=>SHORT")["rules"]
    assert apply_sku_replace_rules("PRINT-MPNLONG-T-BLAC-S", rules) == "DEF-MPNSHORT-T-BLAC-S"
    assert apply_sku_component_replace_rules("PRINT", rules) == "DEF"


def test_invalid_and_duplicate_rules_are_rejected() -> None:
    result = parse_sku_replace_rules("missing separator\n=>EMPTY\nABC=>X\nabc=>Y")
    assert result["valid"] is False
    assert len(result["errors"]) == 3


def test_fingerprint_is_deterministic_and_sensitive_to_rules() -> None:
    rows = [{"folder": "one", "parent_sku": "PRINT-LONG-T"}]
    first = build_sku_replacement_fingerprint(rows, [{"source": "LONG", "replacement": "SHORT"}])
    assert first == build_sku_replacement_fingerprint(rows, [{"source": "LONG", "replacement": "SHORT"}])
    assert first != build_sku_replacement_fingerprint(rows, [{"source": "LONG", "replacement": "X"}])
