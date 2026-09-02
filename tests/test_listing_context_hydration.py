from __future__ import annotations

from types import SimpleNamespace

import app


def _visible_listing_content_state() -> dict[str, object]:
    state: dict[str, object] = {
        "handling_time_days": 2,
        "merchant_shipping_group_name": "INSTOCK Template",
        "sku_decoration_choice": "PRINT",
        "manual_sku_listing_code": "XMBDER",
        "variant_quantity": 100,
        "content_prepared_by": "",
        app.CONTENT_EDITOR_KEYS["title"]: "",
        app.CONTENT_EDITOR_KEYS["description"]: "",
        app.CONTENT_EDITOR_KEYS["keywords"]: "",
    }
    for key in app.CONTENT_EDITOR_KEYS["bullets"]:
        state[key] = ""
    return state


def test_normal_listing_detects_setup_widgets_cleaned_between_tabs() -> None:
    state = _visible_listing_content_state()
    state.pop("manual_sku_listing_code")

    assert app.listing_content_widget_state_is_missing(state, {}) is True


def test_normal_listing_is_hydrated_when_all_visible_widgets_exist() -> None:
    assert (
        app.listing_content_widget_state_is_missing(
            _visible_listing_content_state(),
            {},
        )
        is False
    )


def test_grouped_listing_requires_shared_setup_widgets_not_normal_content_keys() -> None:
    state = _visible_listing_content_state()
    for key in [
        app.CONTENT_EDITOR_KEYS["title"],
        app.CONTENT_EDITOR_KEYS["description"],
        app.CONTENT_EDITOR_KEYS["keywords"],
        *app.CONTENT_EDITOR_KEYS["bullets"],
    ]:
        state.pop(key)
    grouped_memory = {
        "listing_group": {
            "schema_version": 1,
            "group_type": "christmas_project",
            "task_id": "task-1",
            "members": {},
        }
    }

    assert (
        app.listing_content_widget_state_is_missing(state, grouped_memory)
        is False
    )
    state.pop("merchant_shipping_group_name")
    assert (
        app.listing_content_widget_state_is_missing(state, grouped_memory)
        is True
    )


def test_created_task_setup_values_hydrate_listing_content(monkeypatch) -> None:
    session_state: dict[str, object] = {}
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=session_state))
    profile = {
        "sku_decoration_code": "PRINT",
        "colors": ["Black"],
        "sizes": ["S"],
    }
    listing_memory = {
        "merchant_shipping_group_name": "Nationwide Prime",
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "XMBDER",
        "generated_sku_listing_code": "D12345",
        "quantity": 25,
        "handling_time_days": 3,
        "selected_variants": {"color": ["Black"], "size": ["S"]},
        "size_price_map": {"S": 12.99},
    }

    app.apply_listing_memory_to_session(listing_memory, profile)

    assert session_state["merchant_shipping_group_name"] == "Nationwide Prime"
    assert session_state["sku_decoration_choice"] == "PRINT"
    assert session_state["manual_sku_listing_code"] == "XMBDER"
    assert session_state["generated_sku_listing_code"] == "D12345"
    assert session_state["variant_quantity"] == 25
    assert session_state["handling_time_days"] == 3
    assert session_state["selected_colours"] == ["Black"]
    assert session_state["selected_sizes"] == ["S"]
    assert session_state["price_S"] == 12.99


def test_saved_price_normalization_preserves_normal_and_grouped_keys() -> None:
    profile = {
        "saved_variant_value_aliases": {
            "size": {"Small": "S"},
        }
    }

    assert app.normalize_saved_price_map_for_profile(
        profile,
        {
            "Small": 11.99,
            "Adult T-Shirt||Small": 12.99,
        },
    ) == {
        "S": 11.99,
        "Adult T-Shirt||S": 12.99,
    }
