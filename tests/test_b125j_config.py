import json
from pathlib import Path


CONFIG_PATH = Path(__file__).parents[1] / "templates" / "BAG" / "B125J" / "config.json"


def test_b125j_has_required_bag_dimensions_and_valid_capacity_unit():
    profile = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    expected_dimensions = {
        "length_width_side_to_side": "28",
        "length_width_side_to_side_unit_of_measure": "Centimetres",
        "length_height_floor_to_top": "38",
        "length_height_floor_to_top_unit_of_measure": "Centimetres",
        "length_head_to_toe": "19",
        "length_head_to_toe_unit_of_measure": "Centimetres",
    }

    for field_group in ("extra_parent_fields", "extra_child_fields"):
        fields = profile[field_group]
        assert {key: fields.get(key) for key in expected_dimensions} == expected_dimensions
        assert fields["capacity_unit_of_measure"] == "Litres"
