import json
from pathlib import Path


CONFIG_PATH = Path(__file__).parents[1] / "templates" / "BAG" / "B125J" / "config.json"


def test_b125j_uses_amazon_capacity_unit_for_parent_and_children():
    profile = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    for field_group in ("extra_parent_fields", "extra_child_fields"):
        fields = profile[field_group]
        assert fields["capacity"] == "12"
        assert fields["capacity_unit_of_measure"] == "L"
