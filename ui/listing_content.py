from __future__ import annotations

from collections.abc import MutableMapping
from hashlib import sha256
import json
from typing import Any, Callable

import streamlit as st

from services.listing_content_import import parse_listing_content_json
from services.listing_content_prompt import render_amazon_listing_content_prompt
from services.christmas_grouped_content_import import parse_christmas_grouped_content_json
from services.christmas_grouped_content_prompt import render_christmas_grouped_content_prompt
from services.christmas_project_grouping import (
    build_christmas_group_selected_variants,
    derive_christmas_group_members,
    is_grouped_christmas_memory,
    normalize_christmas_grouped_draft,
    normalize_christmas_listing_group,
)


AI_JSON_INPUT_KEY = "listing_content_ai_json_input"
AI_VALIDATION_RESULT_KEY = "listing_content_ai_validation_result"
AI_VALIDATE_BUTTON_KEY = "listing_content_ai_validate_btn"
AI_APPLY_BUTTON_KEY = "listing_content_ai_apply_btn"
AI_JSON_UPLOAD_KEY = "listing_content_ai_json_upload"
AI_PROMPT_DOWNLOAD_KEY = "listing_content_ai_prompt_download_btn"
AI_PROMPT_NOTES_KEY = "listing_content_ai_prompt_notes"
AI_VALIDATED_JSON_DOWNLOAD_KEY = "listing_content_ai_validated_json_download_btn"
GROUPED_EDITOR_CONTEXT_KEY = "grouped_christmas_editor_context"
GROUPED_PRICING_CONTEXT_KEY = "grouped_christmas_pricing_context"
GROUPED_DRAFT_GROUP_KEY = "grouped_christmas_draft_listing_group"
GROUPED_JSON_INPUT_KEY = "grouped_christmas_json_input"
GROUPED_JSON_UPLOAD_KEY = "grouped_christmas_json_upload"
GROUPED_VALIDATION_RESULT_KEY = "grouped_christmas_validation_result"
GROUPED_VALIDATE_BUTTON_KEY = "grouped_christmas_validate_btn"
GROUPED_APPLY_BUTTON_KEY = "grouped_christmas_apply_btn"
GROUPED_TEST_CONTENT_BUTTON_KEY = "grouped_christmas_load_test_content_btn"
GROUPED_PROMPT_NOTES_KEY = "grouped_christmas_prompt_notes"
GROUPED_PROMPT_DOWNLOAD_KEY = "grouped_christmas_prompt_download_btn"
GROUPED_VALIDATED_JSON_DOWNLOAD_KEY = "grouped_christmas_validated_json_download_btn"
GROUPED_VALIDATION_ATTEMPTED_KEY = "grouped_christmas_validation_attempted"


def get_grouped_christmas_content_widget_keys(member_key: str) -> dict[str, Any]:
    prefix = f"grouped_christmas_{member_key}"
    return {
        "title": f"{prefix}_title",
        "bullets": [f"{prefix}_bullet_{index}" for index in range(1, 6)],
        "description": f"{prefix}_product_description",
        "keywords": f"{prefix}_generic_keywords",
    }


def _validated_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _json_download_filename(
    mpn: str,
    suffix: str,
    sanitize_sku: Callable[[str], str],
) -> str:
    safe_mpn = sanitize_sku(str(mpn or "")).upper()
    return f"{safe_mpn}_{suffix}" if safe_mpn else suffix


def initialize_grouped_christmas_editor_state(
    *,
    profile: dict[str, Any],
    listing_memory: dict[str, Any],
    session_state: MutableMapping[str, Any],
) -> dict[str, Any]:
    listing_group = normalize_christmas_listing_group(
        profile,
        listing_memory.get("listing_group", {}),
    )
    editor_context = json.dumps(listing_group, sort_keys=True, ensure_ascii=False)
    if session_state.get(GROUPED_EDITOR_CONTEXT_KEY) != editor_context:
        for member_key, member in listing_group["members"].items():
            keys = get_grouped_christmas_content_widget_keys(member_key)
            content = member["content"]
            session_state[keys["title"]] = content["title"]
            for key, value in zip(keys["bullets"], content["bullet_points"]):
                session_state[key] = value
            session_state[keys["description"]] = content["product_description"]
            session_state[keys["keywords"]] = content["generic_keywords"]
        session_state[GROUPED_EDITOR_CONTEXT_KEY] = editor_context
        session_state[GROUPED_DRAFT_GROUP_KEY] = listing_group

    pricing_context = json.dumps(
        {
            "task_id": listing_group["task_id"],
            "size_price_map": listing_memory.get("size_price_map", {}),
            "price_input_mode": listing_memory.get("price_input_mode", ""),
            "use_same_price_for_all_sizes": listing_memory.get("use_same_price_for_all_sizes", False),
        },
        sort_keys=True,
    )
    if session_state.get(GROUPED_PRICING_CONTEXT_KEY) != pricing_context:
        for key in list(session_state):
            if str(key).startswith(("cluster_price_", "price_", "size_cluster_price_")):
                session_state.pop(key, None)
        saved_mode = str(listing_memory.get("price_input_mode", "") or "").strip()
        session_state["design_size_pricing_mode"] = saved_mode or "Use one price per cluster"
        session_state["use_same_price_for_all_sizes"] = bool(
            listing_memory.get("use_same_price_for_all_sizes", False)
        )
        session_state.pop("shared_price_all_sizes", None)
        session_state[GROUPED_PRICING_CONTEXT_KEY] = pricing_context

    return listing_group


def _render_grouped_member_content(member_key: str, label: str) -> dict[str, Any]:
    keys = get_grouped_christmas_content_widget_keys(member_key)
    with st.expander(label, expanded=True):
        title = st.text_input("Product title", key=keys["title"])
        bullets = [
            st.text_input(f"Bullet {index}", key=key)
            for index, key in enumerate(keys["bullets"], start=1)
        ]
        product_description = st.text_area(
            "Product description",
            height=120,
            key=keys["description"],
        )
        generic_keywords = st.text_area(
            "Search terms",
            height=100,
            key=keys["keywords"],
        )
        st.caption(
            f"Title {len(title.strip())} chars; description {len(product_description.strip())} chars; "
            f"search terms {len(generic_keywords.encode('utf-8'))}/249 bytes."
        )
    return {
        "title": title,
        "bullet_points": bullets,
        "product_description": product_description,
        "generic_keywords": generic_keywords,
    }


def apply_validated_grouped_christmas_content(
    *,
    validation_record: Any,
    current_raw_text: str,
    current_source_identity: str,
    profile: dict[str, Any],
    listing_group: dict[str, Any],
    session_state: MutableMapping[str, Any],
) -> bool:
    if not isinstance(validation_record, dict):
        return False
    if validation_record.get("raw_text") != current_raw_text:
        return False
    if validation_record.get("source_identity") != current_source_identity:
        return False

    result = validation_record.get("result")
    if not isinstance(result, dict) or not result.get("valid"):
        return False
    members = result.get("members")
    if not isinstance(members, dict) or set(members) != {"tshirt", "sweatshirt", "hoodie"}:
        return False

    for member_key, content in members.items():
        keys = get_grouped_christmas_content_widget_keys(member_key)
        session_state[keys["title"]] = content["title"]
        for key, value in zip(keys["bullets"], content["bullet_points"]):
            session_state[key] = value
        session_state[keys["description"]] = content["product_description"]
        session_state[keys["keywords"]] = content["generic_keywords"]

    session_state[GROUPED_DRAFT_GROUP_KEY] = normalize_christmas_grouped_draft(
        profile,
        {"listing_group": listing_group},
        members,
    )["listing_group"]
    return True


def render_grouped_christmas_content_import(
    *,
    profile: dict[str, Any],
    listing_group: dict[str, Any],
    dev_tools_enabled: bool,
    load_grouped_test_json: Callable[[], str],
    mpn: str,
    sanitize_sku: Callable[[str], str],
) -> None:
    with st.expander("Import grouped listing content", expanded=False):
        st.markdown("**Generate with ChatGPT**")
        st.caption(
            "Use one representative design/mockup image with this prompt to generate all three: "
            "T-Shirt, Sweatshirt and Hoodie, even if the image shows only one garment."
        )
        st.write(f"MPN: {mpn or '[not available]'}")
        prompt_notes = st.text_area(
            "Optional notes",
            key=GROUPED_PROMPT_NOTES_KEY,
        )
        safe_mpn = sanitize_sku(mpn).upper() or "CHRISTMAS"
        grouped_json_filename = _json_download_filename(
            mpn,
            "christmas_grouped_listing_content.json",
            sanitize_sku,
        )
        try:
            prompt_text = render_christmas_grouped_content_prompt(
                mpn,
                prompt_notes,
                output_filename=grouped_json_filename,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            st.error(f"The grouped ChatGPT prompt is currently unavailable: {exc}")
        else:
            st.download_button(
                "Download grouped ChatGPT prompt",
                data=prompt_text,
                file_name=f"{safe_mpn}_christmas_grouped_chatgpt_prompt.txt",
                mime="text/plain",
                key=GROUPED_PROMPT_DOWNLOAD_KEY,
            )

        if dev_tools_enabled and st.button(
            "Load test Christmas content",
            key=GROUPED_TEST_CONTENT_BUTTON_KEY,
        ):
            try:
                test_raw_text = load_grouped_test_json()
                st.session_state[GROUPED_JSON_INPUT_KEY] = test_raw_text
                st.session_state.pop(GROUPED_JSON_UPLOAD_KEY, None)
                test_source = resolve_listing_content_import_source(test_raw_text)
                validation_record = {
                    "raw_text": test_source["raw_text"],
                    "source_identity": test_source["source_identity"],
                    "result": parse_christmas_grouped_content_json(test_source["raw_text"]),
                }
                st.session_state[GROUPED_VALIDATION_RESULT_KEY] = validation_record
                st.session_state[GROUPED_VALIDATION_ATTEMPTED_KEY] = True
                if apply_validated_grouped_christmas_content(
                    validation_record=validation_record,
                    current_raw_text=test_source["raw_text"],
                    current_source_identity=test_source["source_identity"],
                    profile=profile,
                    listing_group=listing_group,
                    session_state=st.session_state,
                ):
                    st.success("Loaded valid synthetic content into all three Christmas families.")
                else:
                    st.error("The bundled test content did not pass grouped validation.")
            except (OSError, UnicodeError) as exc:
                st.error(f"Could not load test Christmas content: {exc}")

        uploaded_file = _render_grouped_json_file_uploader()
        st.caption("OR")
        pasted_text = st.text_area(
            "Grouped listing content JSON",
            height=220,
            key=GROUPED_JSON_INPUT_KEY,
        )
        import_source = resolve_listing_content_import_source(pasted_text, uploaded_file)
        st.caption(f"Current source: {import_source['source_label']}")
        source_error = str(import_source.get("error", "") or "")
        if source_error:
            st.error(source_error)

        if st.button(
            "Validate grouped JSON",
            key=GROUPED_VALIDATE_BUTTON_KEY,
            disabled=bool(source_error),
        ):
            st.session_state[GROUPED_VALIDATION_ATTEMPTED_KEY] = True
            st.session_state[GROUPED_VALIDATION_RESULT_KEY] = {
                "raw_text": import_source["raw_text"],
                "source_identity": import_source["source_identity"],
                "result": parse_christmas_grouped_content_json(import_source["raw_text"]),
            }

        if source_error:
            return
        if not st.session_state.get(GROUPED_VALIDATION_ATTEMPTED_KEY, False):
            return
        validation_record = st.session_state.get(GROUPED_VALIDATION_RESULT_KEY)
        if not isinstance(validation_record, dict):
            return

        raw_text = import_source["raw_text"]
        source_identity = import_source["source_identity"]
        if (
            validation_record.get("raw_text") != raw_text
            or validation_record.get("source_identity") != source_identity
        ):
            st.warning("The current grouped import source has changed. Validate it again before applying.")
            return

        result = validation_record.get("result", {})
        if not isinstance(result, dict):
            return
        for error in result.get("errors", []):
            st.error(error)
        for warning in result.get("warnings", []):
            st.warning(warning)
        if not result.get("valid"):
            return

        for member_key, label in [
            ("tshirt", "T-Shirt"),
            ("sweatshirt", "Sweatshirt"),
            ("hoodie", "Hoodie"),
        ]:
            content = result["members"][member_key]
            st.markdown(f"**{label}**")
            st.write(content["title"])
            for index, bullet in enumerate(content["bullet_points"], start=1):
                st.write(f"{index}. {bullet}")

        normalized_grouped_json = {
            "schema_version": 1,
            "group_type": "christmas_project",
            "members": result["members"],
        }
        st.download_button(
            "Download validated JSON",
            data=_validated_json_text(normalized_grouped_json),
            file_name=_json_download_filename(
                mpn,
                "christmas_grouped_listing_content.json",
                sanitize_sku,
            ),
            mime="application/json",
            key=GROUPED_VALIDATED_JSON_DOWNLOAD_KEY,
        )

        if st.button(
            "Apply to all 3 families",
            key=GROUPED_APPLY_BUTTON_KEY,
        ) and apply_validated_grouped_christmas_content(
            validation_record=validation_record,
            current_raw_text=raw_text,
            current_source_identity=source_identity,
            profile=profile,
            listing_group=listing_group,
            session_state=st.session_state,
        ):
            st.success("Applied validated content to all three Christmas families.")


def render_grouped_christmas_listing_content(
    *,
    staged_folder_name: str | None,
    listing_memory: dict[str, Any],
    profile: dict[str, Any],
    merchant_shipping_group_options: list[str],
    sku_decoration_options: list[str],
    workflow_assignees: list[str],
    normalize_merchant_shipping_group: Callable[..., str],
    selectbox_index_without_state_conflict: Callable[..., int],
    get_default_sku_decoration_code: Callable[..., str],
    sanitize_sku: Callable[[str], str],
    get_or_create_generated_sku_listing_code: Callable[..., str],
    build_parent_sku_from_context: Callable[..., str],
    build_size_price_inputs: Callable[..., dict[str, float]],
    load_grouped_image_manifest: Callable[..., dict[str, Any]],
    save_grouped_draft: Callable[..., str],
    dev_tools_enabled: bool,
    load_grouped_test_json: Callable[[], str],
) -> dict[str, Any]:
    listing_group = initialize_grouped_christmas_editor_state(
        profile=profile,
        listing_memory=listing_memory,
        session_state=st.session_state,
    )
    members = derive_christmas_group_members(profile)
    selected_variants = build_christmas_group_selected_variants(profile)

    st.subheader("Christmas Project")
    st.caption("One staged draft containing three future Amazon listings.")
    summary_columns = st.columns(3)
    for column, member in zip(summary_columns, members.values()):
        with column:
            st.markdown(f"**{member['label']}**")
            st.write(" / ".join(member["designs"]))

    render_grouped_christmas_content_import(
        profile=profile,
        listing_group=listing_group,
        dev_tools_enabled=dev_tools_enabled,
        load_grouped_test_json=load_grouped_test_json,
        mpn=str(listing_memory.get("mpn", "") or staged_folder_name or "").strip(),
        sanitize_sku=sanitize_sku,
    )

    st.subheader("Listing content by family")
    member_contents = {
        member_key: _render_grouped_member_content(member_key, member["label"])
        for member_key, member in members.items()
    }

    st.subheader("Fulfillment")
    fulfillment_col1, fulfillment_col2 = st.columns(2)
    with fulfillment_col1:
        handling_time_days = st.number_input(
            "Handling time",
            min_value=0,
            step=1,
            key="handling_time_days",
            help="Writes fulfillment lead time for child rows. Default is 2.",
        )
    with fulfillment_col2:
        current_shipping_group = normalize_merchant_shipping_group(
            st.session_state.get("merchant_shipping_group_name", "")
        )
        st.selectbox(
            "Merchant Shipping Group",
            merchant_shipping_group_options,
            index=selectbox_index_without_state_conflict(
                "merchant_shipping_group_name",
                merchant_shipping_group_options,
                current_shipping_group,
            ),
            key="merchant_shipping_group_name",
            help="Leave empty to skip this Amazon field.",
        )

    st.subheader("Variants")
    st.write(
        f"{len(selected_variants['design'])} designs, "
        f"{len(selected_variants['color'])} configured colours, "
        f"{len(selected_variants['size'])} configured sizes."
    )
    for member in members.values():
        st.caption(
            f"{member['label']}: {', '.join(member['allowed_colours'])}; "
            + "; ".join(
                f"{design}: {', '.join(sizes)}"
                for design, sizes in member["sizes_by_design"].items()
            )
        )

    st.subheader("SKU setup")
    default_sku_decoration_code = get_default_sku_decoration_code(profile, listing_memory)
    st.session_state.setdefault(
        "sku_decoration_choice",
        default_sku_decoration_code if default_sku_decoration_code in sku_decoration_options else "Custom",
    )
    st.session_state.setdefault(
        "custom_sku_decoration_code",
        "" if default_sku_decoration_code in sku_decoration_options else default_sku_decoration_code,
    )
    sku_decoration_choice = st.selectbox(
        "Decoration code",
        sku_decoration_options,
        key="sku_decoration_choice",
    )
    if sku_decoration_choice == "Custom":
        custom_sku_decoration_code = st.text_input(
            "Custom decoration code",
            key="custom_sku_decoration_code",
        )
        sku_decoration_code = sanitize_sku(custom_sku_decoration_code).upper()
    else:
        sku_decoration_code = sku_decoration_choice

    generated_sku_listing_code = sanitize_sku(
        get_or_create_generated_sku_listing_code(listing_memory)
    ).upper()
    manual_sku_listing_code = sanitize_sku(st.text_input(
        "Listing/design code (optional)",
        key="manual_sku_listing_code",
        placeholder=generated_sku_listing_code,
        help="Leave blank to use the generated unique design identifier.",
    )).upper()
    sku_listing_code = manual_sku_listing_code or generated_sku_listing_code
    parent_sku_for_listing = build_parent_sku_from_context(
        profile,
        sku_decoration_code,
        sku_listing_code,
    )
    st.caption(f"Parent SKU: `{parent_sku_for_listing}`")

    size_price_map = build_size_price_inputs(
        selected_variants["size"],
        saved_prices=listing_memory.get("size_price_map", {}),
        profile=profile,
        selected_variants=selected_variants,
    )
    st.session_state["current_size_price_map"] = dict(size_price_map)

    st.subheader("Inventory setup")
    quantity = st.number_input(
        "Quantity for all child variants",
        min_value=1,
        step=1,
        key="variant_quantity",
    )
    st.selectbox(
        "Content prepared by",
        workflow_assignees,
        key="content_prepared_by",
    )

    st.subheader("Grouped image readiness")
    image_state_key = f"grouped_christmas_image_manifest_{listing_group['task_id']}"
    if st.button(
        "Refresh grouped image readiness",
        key="grouped_christmas_refresh_images_btn",
        disabled=not bool(staged_folder_name),
    ):
        try:
            st.session_state[image_state_key] = load_grouped_image_manifest(
                staged_folder_name or "",
                profile,
            )
        except Exception as exc:
            st.error(f"Could not refresh grouped image readiness: {exc}")

    image_manifest = st.session_state.get(image_state_key)
    if isinstance(image_manifest, dict):
        image_columns = st.columns(3)
        for column, (member_key, member) in zip(image_columns, members.items()):
            member_manifest = image_manifest.get("members", {}).get(member_key, {})
            ready_count = len(member_manifest.get("images_by_colour", {}))
            expected_count = len(member["allowed_colours"])
            with column:
                st.markdown(f"**{member['label']}**")
                st.write(f"{ready_count} / {expected_count}")
        for error in image_manifest.get("errors", []):
            st.error(error)
        for member_key, member_manifest in image_manifest.get("members", {}).items():
            missing = member_manifest.get("missing_colours", [])
            if missing:
                st.warning(f"{members[member_key]['label']} missing: {', '.join(missing)}")
    else:
        st.caption("Refresh when staged images are ready to check the configured 7 / 7 / 2 coverage.")

    draft_payload = dict(listing_memory)
    draft_payload.update({
        "selected_variants": selected_variants,
        "size_price_map": dict(size_price_map),
        "price_input_mode": st.session_state.get(
            "design_size_pricing_mode",
            listing_memory.get("price_input_mode", "Use one price per cluster"),
        ),
        "use_same_price_for_all_sizes": st.session_state.get("use_same_price_for_all_sizes", False),
        "quantity": quantity,
        "handling_time_days": handling_time_days,
        "merchant_shipping_group_name": normalize_merchant_shipping_group(
            st.session_state.get("merchant_shipping_group_name", "")
        ),
        "sku_decoration_code": sku_decoration_code,
        "manual_sku_listing_code": manual_sku_listing_code,
        "generated_sku_listing_code": generated_sku_listing_code,
        "sku_listing_code": sku_listing_code,
        "base_parent_sku": profile.get("parent_sku", ""),
        "parent_sku": parent_sku_for_listing,
        "content_prepared_by": st.session_state.get("content_prepared_by", ""),
    })
    draft_payload = normalize_christmas_grouped_draft(
        profile,
        draft_payload,
        member_contents,
    )
    st.session_state[GROUPED_DRAFT_GROUP_KEY] = draft_payload["listing_group"]

    action_columns = st.columns(2)
    save_clicked = action_columns[0].button(
        "Save Draft",
        key="grouped_christmas_save_draft_btn",
        width="stretch",
        disabled=not bool(staged_folder_name),
    )
    action_columns[1].button(
        "Submit for Review",
        key="grouped_christmas_submit_for_review_btn",
        width="stretch",
        disabled=True,
    )
    st.info("Grouped Christmas submission will be enabled after grouped review fan-out is available.")
    if save_clicked:
        try:
            saved_path = save_grouped_draft(
                profile,
                draft_payload,
                staged_folder_name or "",
            )
            st.success(f"Saved grouped draft to {saved_path}.")
        except Exception as exc:
            st.error(f"Could not save grouped draft: {exc}")

    return {
        "title": str(listing_memory.get("title", "") or ""),
        "bullets": list(listing_memory.get("bullet_points", []) or []),
        "product_description": str(listing_memory.get("product_description", "") or ""),
        "generic_keywords": str(listing_memory.get("generic_keywords", "") or ""),
        "handling_time_days": handling_time_days,
        "selected_variants": selected_variants,
        "sku_decoration_code": sku_decoration_code,
        "manual_sku_listing_code": manual_sku_listing_code,
        "generated_sku_listing_code": generated_sku_listing_code,
        "sku_listing_code": sku_listing_code,
        "parent_sku_for_listing": parent_sku_for_listing,
        "size_price_map": size_price_map,
        "quantity": quantity,
        "score_clicked": False,
        "ready_clicked": False,
        "content_debug_container": st.container(),
        "content_preflight_container": st.container(),
        "content_action_result_container": st.container(),
    }


def resolve_listing_content_import_source(
    pasted_text: str,
    uploaded_file: Any = None,
) -> dict[str, Any]:
    if uploaded_file is None:
        raw_bytes = pasted_text.encode("utf-8")
        return {
            "raw_text": pasted_text,
            "source_identity": f"paste:{sha256(raw_bytes).hexdigest()}",
            "source_label": "pasted JSON",
            "error": "",
        }

    raw_bytes = uploaded_file.getvalue()
    filename = str(getattr(uploaded_file, "name", "uploaded.json") or "uploaded.json")
    source_identity = f"upload:{filename}:{sha256(raw_bytes).hexdigest()}"
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "raw_text": None,
            "source_identity": source_identity,
            "source_label": f"uploaded JSON file: {filename}",
            "error": "The uploaded JSON file is not valid UTF-8 text.",
        }

    return {
        "raw_text": raw_text,
        "source_identity": source_identity,
        "source_label": f"uploaded JSON file: {filename}",
        "error": "",
    }


def apply_validated_listing_content(
    validation_record: Any,
    current_raw_text: str,
    content_editor_keys: dict[str, Any],
    session_state: MutableMapping[str, Any],
    sync_content_editor_to_canonical_state: Callable[..., None],
    current_source_identity: str | None = None,
) -> bool:
    if not isinstance(validation_record, dict):
        return False
    if validation_record.get("raw_text") != current_raw_text:
        return False
    if (
        current_source_identity is not None
        and validation_record.get("source_identity") != current_source_identity
    ):
        return False

    result = validation_record.get("result")
    if not isinstance(result, dict) or not result.get("valid"):
        return False

    content = result.get("content")
    if not isinstance(content, dict):
        return False
    bullets = content.get("bullet_points")
    if not isinstance(bullets, list) or len(bullets) != 5:
        return False

    title = content.get("title", "")
    product_description = content.get("product_description", "")
    generic_keywords = content.get("generic_keywords", "")
    session_state[content_editor_keys["title"]] = title
    session_state[content_editor_keys["description"]] = product_description
    session_state[content_editor_keys["keywords"]] = generic_keywords
    for index, bullet in enumerate(bullets):
        session_state[content_editor_keys["bullets"][index]] = bullet

    sync_content_editor_to_canonical_state(
        title,
        bullets,
        product_description,
        generic_keywords,
    )
    return True


def render_chatgpt_prompt_download(
    *,
    mpn: str,
    sanitize_sku: Callable[[str], str],
) -> None:
    st.markdown("**Generate with ChatGPT**")
    st.caption(
        "Upload your product/design image to ChatGPT, use our standard prompt, "
        "then upload or paste the returned JSON below."
    )
    st.write(f"MPN: {mpn or '[not available]'}")
    prompt_notes = st.text_area(
        "Optional notes",
        key=AI_PROMPT_NOTES_KEY,
    )
    output_filename = _json_download_filename(
        mpn,
        "amazon_listing_content.json",
        sanitize_sku,
    )
    try:
        prompt_text = render_amazon_listing_content_prompt(
            mpn,
            prompt_notes,
            output_filename=output_filename,
        )
    except (OSError, UnicodeError, ValueError):
        st.error("The standard ChatGPT prompt is currently unavailable.")
        return

    st.download_button(
        "Download ChatGPT Prompt",
        data=prompt_text,
        file_name="amazon_listing_content_chatgpt_prompt.txt",
        mime="text/plain",
        key=AI_PROMPT_DOWNLOAD_KEY,
    )


def render_ai_listing_content_import(
    *,
    content_editor_keys: dict[str, Any],
    sync_content_editor_to_canonical_state: Callable[..., None],
    mpn: str,
    sanitize_sku: Callable[[str], str],
) -> None:
    with st.expander("Import AI listing content", expanded=False):
        render_chatgpt_prompt_download(mpn=mpn, sanitize_sku=sanitize_sku)

        uploaded_file = st.file_uploader(
            "Upload JSON file",
            type=["json"],
            key=AI_JSON_UPLOAD_KEY,
        )
        st.caption("OR")
        pasted_text = st.text_area(
            "AI listing content JSON",
            height=220,
            key=AI_JSON_INPUT_KEY,
        )
        import_source = resolve_listing_content_import_source(pasted_text, uploaded_file)
        st.caption(f"Current source: {import_source['source_label']}")
        source_error = str(import_source.get("error", "") or "")
        if source_error:
            st.error(source_error)

        validate_clicked = st.button(
            "Validate JSON",
            key=AI_VALIDATE_BUTTON_KEY,
            disabled=bool(source_error),
        )
        if validate_clicked:
            st.session_state[AI_VALIDATION_RESULT_KEY] = {
                "raw_text": import_source["raw_text"],
                "source_identity": import_source["source_identity"],
                "result": parse_listing_content_json(import_source["raw_text"]),
            }

        if source_error:
            return

        validation_record = st.session_state.get(AI_VALIDATION_RESULT_KEY)
        if not isinstance(validation_record, dict):
            return

        raw_text = import_source["raw_text"]
        source_identity = import_source["source_identity"]
        is_stale = (
            validation_record.get("raw_text") != raw_text
            or validation_record.get("source_identity") != source_identity
        )
        if is_stale:
            st.warning("The current import source has changed. Validate it again before applying.")
            return

        result = validation_record.get("result", {})
        if not isinstance(result, dict):
            return

        for error in result.get("errors", []):
            st.error(error)
        for warning in result.get("warnings", []):
            st.warning(warning)

        if not result.get("valid"):
            return

        content = result.get("content", {})
        if not isinstance(content, dict):
            return

        st.markdown("**Title**")
        st.write(content.get("title", ""))
        st.markdown("**Bullet points**")
        for index, bullet in enumerate(content.get("bullet_points", []), start=1):
            st.write(f"{index}. {bullet}")
        st.markdown("**Product description**")
        st.write(content.get("product_description", ""))
        st.markdown("**Search terms**")
        st.write(content.get("generic_keywords", ""))

        st.download_button(
            "Download validated JSON",
            data=_validated_json_text(content),
            file_name=_json_download_filename(
                mpn,
                "amazon_listing_content.json",
                sanitize_sku,
            ),
            mime="application/json",
            key=AI_VALIDATED_JSON_DOWNLOAD_KEY,
        )

        apply_clicked = st.button(
            "Apply to Listing Content",
            key=AI_APPLY_BUTTON_KEY,
        )
        if apply_clicked and apply_validated_listing_content(
            validation_record,
            raw_text,
            content_editor_keys,
            st.session_state,
            sync_content_editor_to_canonical_state,
            current_source_identity=source_identity,
        ):
            st.success("Applied AI content to the editable Listing Content fields.")


def _render_grouped_json_file_uploader() -> Any:
    grouped_file_uploader = st.file_uploader
    return grouped_file_uploader(
        "Upload grouped JSON file",
        type=["json"],
        key=GROUPED_JSON_UPLOAD_KEY,
    )


def render_listing_content(
    *,
    active_staged_folder_name: str,
    active_template_label: str,
    selected_parent_main_label: str,
    preview_parent_main_image_url: str,
    preview_color_image_map: dict[str, str],
    preview_design_color_image_url_map: dict[str, dict[str, str]],
    preview_other_images: list[str],
    image_mapping_status: str,
    image_mapping_detail: str,
    staged_folder_name: str | None,
    listing_memory: dict[str, Any],
    active_profile: dict[str, Any],
    profile: dict[str, Any],
    memory_fingerprint: str,
    CONTENT_EDITOR_KEYS: dict[str, Any],
    MERCHANT_SHIPPING_GROUP_OPTIONS: list[str],
    SKU_DECORATION_OPTIONS: list[str],
    WORKFLOW_ASSIGNEES: list[str],
    variant_dimensions: list[dict[str, Any]],
    selected_variants: dict[str, list[str]],
    colors_available: list[str],
    full_preview_color_image_map: dict[str, str],
    full_preview_design_color_image_url_map: dict[str, dict[str, str]],
    auto_apply_mapped_colors: bool,
    image_mapping_context_key: str,
    render_active_product_context: Callable[..., None],
    listing_memory_has_content: Callable[..., bool],
    apply_listing_memory_to_session: Callable[..., None],
    words_repeated_at_least: Callable[..., list[str]],
    find_forbidden_title_phrases_for_app: Callable[..., list[str]],
    sync_content_editor_to_canonical_state: Callable[..., None],
    trim_search_terms: Callable[..., str],
    normalize_merchant_shipping_group: Callable[..., str],
    selectbox_index_without_state_conflict: Callable[..., int],
    get_mapped_color_options: Callable[..., list[str]],
    apply_mapped_colors_to_widget_once: Callable[..., None],
    get_available_sizes_for_selected_colors: Callable[..., list[str]],
    normalize_multiselect_values: Callable[..., tuple[list[str], bool]],
    get_default_sku_decoration_code: Callable[..., str],
    sanitize_sku: Callable[..., str],
    get_or_create_generated_sku_listing_code: Callable[..., str],
    build_parent_sku_from_context: Callable[..., str],
    render_variant_combinations_preview: Callable[..., None],
    build_size_price_inputs: Callable[..., dict[str, float]],
    load_grouped_image_manifest: Callable[..., dict[str, Any]],
    save_grouped_draft: Callable[..., str],
    dev_tools_enabled: bool,
    load_grouped_test_json: Callable[[], str],
) -> dict[str, Any]:
    render_active_product_context(
        active_staged_folder_name=active_staged_folder_name,
        active_template_label=active_template_label,
        selected_parent_main_label=selected_parent_main_label,
        preview_parent_main_image_url=preview_parent_main_image_url,
        preview_color_image_map=preview_color_image_map,
        preview_design_color_image_url_map=preview_design_color_image_url_map,
        preview_other_images=preview_other_images,
        image_mapping_status=image_mapping_status,
        image_mapping_detail=image_mapping_detail,
    )

    if is_grouped_christmas_memory(listing_memory):
        return render_grouped_christmas_listing_content(
            staged_folder_name=staged_folder_name,
            listing_memory=listing_memory,
            profile=profile,
            merchant_shipping_group_options=MERCHANT_SHIPPING_GROUP_OPTIONS,
            sku_decoration_options=SKU_DECORATION_OPTIONS,
            workflow_assignees=WORKFLOW_ASSIGNEES,
            normalize_merchant_shipping_group=normalize_merchant_shipping_group,
            selectbox_index_without_state_conflict=selectbox_index_without_state_conflict,
            get_default_sku_decoration_code=get_default_sku_decoration_code,
            sanitize_sku=sanitize_sku,
            get_or_create_generated_sku_listing_code=get_or_create_generated_sku_listing_code,
            build_parent_sku_from_context=build_parent_sku_from_context,
            build_size_price_inputs=build_size_price_inputs,
            load_grouped_image_manifest=load_grouped_image_manifest,
            save_grouped_draft=save_grouped_draft,
            dev_tools_enabled=dev_tools_enabled,
            load_grouped_test_json=load_grouped_test_json,
        )

    if staged_folder_name and listing_memory_has_content(listing_memory):
        fill_col, info_col = st.columns([1, 3])
        with fill_col:
            fill_from_json_clicked = st.button(
                "Fill fields from listing_inputs.json",
                key="fill_listing_content_from_json_btn",
                width="stretch",
                help="Use this when a restaged folder has saved content but the editable fields are blank.",
            )
        with info_col:
            st.caption(
                "Saved content is available for this staged folder. "
                "Click the button if the editable fields did not hydrate automatically."
            )

        if fill_from_json_clicked:
            apply_listing_memory_to_session(listing_memory, active_profile)
            current_memory_fingerprint = memory_fingerprint
            if current_memory_fingerprint:
                st.session_state["applied_listing_memory_key_v2"] = current_memory_fingerprint
                st.session_state["applied_listing_memory_widget_key_v2"] = current_memory_fingerprint
            st.success("Filled editable content fields from listing_inputs.json.")

    if str(profile.get("template_key", "") or "").strip().upper() == "CP":
        st.info(
            "This is the standard single-listing content importer. Select a grouped Christmas "
            "staged task to generate T-Shirt, Sweatshirt and Hoodie content together."
        )

    render_ai_listing_content_import(
        content_editor_keys=CONTENT_EDITOR_KEYS,
        sync_content_editor_to_canonical_state=sync_content_editor_to_canonical_state,
        mpn=str(listing_memory.get("mpn", "") or staged_folder_name or "").strip(),
        sanitize_sku=sanitize_sku,
    )

    title = st.text_input(
        "Product title",
        key=CONTENT_EDITOR_KEYS["title"],
    )
    if st.session_state.get("show_header_debug", False):
        st.caption(f"Loaded title debug: {title or '[empty]'}")

    title_chars = len(title.strip())
    if title_chars < 150:
        st.caption(f"Title: {title_chars} chars - target 150 chars")
    else:
        st.caption(f"Title: {title_chars} chars - good")
    repeated_title_words = words_repeated_at_least(title, 3)
    if repeated_title_words:
        st.error(
            "Amazon may reject titles where one word appears 3+ times: "
            + ", ".join(repeated_title_words[:8])
        )
    forbidden_title_phrases = find_forbidden_title_phrases_for_app(title)
    if forbidden_title_phrases:
        st.error(
            "Amazon rejected phrase in title: "
            + ", ".join(forbidden_title_phrases)
        )

    st.subheader("Bullets")
    bullets = [
        st.text_input("Bullet 1", key=CONTENT_EDITOR_KEYS["bullets"][0]),
        st.text_input("Bullet 2", key=CONTENT_EDITOR_KEYS["bullets"][1]),
        st.text_input("Bullet 3", key=CONTENT_EDITOR_KEYS["bullets"][2]),
        st.text_input("Bullet 4", key=CONTENT_EDITOR_KEYS["bullets"][3]),
        st.text_input("Bullet 5", key=CONTENT_EDITOR_KEYS["bullets"][4]),
    ]

    for idx, bullet in enumerate(bullets, start=1):
        bullet_len = len(bullet.strip())
        if bullet_len < 150:
            st.caption(f"Bullet {idx}: {bullet_len} chars - target 150+")
        else:
            st.caption(f"Bullet {idx}: {bullet_len} chars - good")

    st.subheader("Description and search terms")
    product_description = st.text_area(
        "Product description",
        height=120,
        key=CONTENT_EDITOR_KEYS["description"],
    )

    description_chars = len(product_description.strip())
    if description_chars < 1000:
        st.caption(f"Description: {description_chars} chars - target 1000 to 2000")
    elif description_chars <= 2000:
        st.caption(f"Description: {description_chars} chars - good")
    else:
        st.error(f"Description: {description_chars} chars - must be under 2000")

    generic_keywords = st.text_area(
        "Search terms",
        height=100,
        key=CONTENT_EDITOR_KEYS["keywords"],
    )
    sync_content_editor_to_canonical_state(
        title,
        bullets,
        product_description,
        generic_keywords,
    )

    byte_count = len(generic_keywords.encode("utf-8"))
    max_bytes = 249

    if byte_count < max_bytes * 0.8:
        st.caption(f"{byte_count}/{max_bytes} bytes")
    elif byte_count <= max_bytes:
        st.warning(f"{byte_count}/{max_bytes} bytes (near limit)")
    else:
        st.error(f"{byte_count}/{max_bytes} bytes (too long)")

    trimmed_keywords = trim_search_terms(generic_keywords)
    if trimmed_keywords != generic_keywords.strip():
        st.warning("Search terms will be trimmed to fit Amazon limit:")
        st.code(trimmed_keywords)

    st.subheader("Fulfillment")
    fulfillment_col1, fulfillment_col2 = st.columns(2)
    with fulfillment_col1:
        handling_time_days = st.number_input(
            "Handling time",
            min_value=0,
            step=1,
            key="handling_time_days",
            help="Writes fulfillment lead time for child rows. Default is 2.",
        )
    with fulfillment_col2:
        current_shipping_group = normalize_merchant_shipping_group(
            st.session_state.get("merchant_shipping_group_name", "")
        )
        st.selectbox(
            "Merchant Shipping Group",
            MERCHANT_SHIPPING_GROUP_OPTIONS,
            index=selectbox_index_without_state_conflict(
                "merchant_shipping_group_name",
                MERCHANT_SHIPPING_GROUP_OPTIONS,
                current_shipping_group,
            ),
            key="merchant_shipping_group_name",
            help="Leave empty to skip this Amazon field.",
        )

    st.subheader("Variants")

    if variant_dimensions:
        selected_variants = {}
        for dim in variant_dimensions:
            dim_name = dim.get("name", "")
            dim_label = dim.get("label", dim_name.title())
            dim_options = dim.get("options", [])
            widget_key = f"variant_{dim_name}"
            if str(dim_name).strip().lower() in {"color", "colour"}:
                mapped_colors = get_mapped_color_options(
                    list(dim_options),
                    full_preview_color_image_map,
                    full_preview_design_color_image_url_map,
                )
                if auto_apply_mapped_colors:
                    apply_mapped_colors_to_widget_once(
                        widget_key,
                        mapped_colors,
                        image_mapping_context_key,
                        allow_replace_existing=True,
                    )
                action_cols = st.columns(3)
                if action_cols[0].button("All colours", key=f"{widget_key}_all", width="stretch"):
                    st.session_state[widget_key] = list(dim_options)
                    st.rerun()
                if action_cols[1].button("No colours", key=f"{widget_key}_none", width="stretch"):
                    st.session_state[widget_key] = []
                    st.rerun()
                if action_cols[2].button(
                    "Mapped colours",
                    key=f"{widget_key}_mapped",
                    width="stretch",
                    disabled=not bool(staged_folder_name),
                    help="Select only colours that have staged images mapped by filename.",
                ):
                    if mapped_colors:
                        st.session_state[widget_key] = list(mapped_colors)
                        st.rerun()
                    else:
                        st.session_state["apply_mapped_colours_widget_key"] = widget_key
                        st.session_state["scan_mapped_colours_now"] = True
                        st.rerun()

            selected_variants[dim_name] = st.multiselect(
                dim_label,
                dim_options,
                key=widget_key,
            )
    else:
        mapped_colors = get_mapped_color_options(
            list(colors_available),
            full_preview_color_image_map,
            full_preview_design_color_image_url_map,
        )
        if auto_apply_mapped_colors:
            apply_mapped_colors_to_widget_once(
                "selected_colours",
                mapped_colors,
                image_mapping_context_key,
                allow_replace_existing=True,
            )
        color_action_cols = st.columns(3)
        if color_action_cols[0].button("All colours", key="selected_colours_all", width="stretch"):
            st.session_state["selected_colours"] = list(colors_available)
            st.rerun()
        if color_action_cols[1].button("No colours", key="selected_colours_none", width="stretch"):
            st.session_state["selected_colours"] = []
            st.rerun()
        if color_action_cols[2].button(
            "Mapped colours",
            key="selected_colours_mapped",
            width="stretch",
            disabled=not bool(staged_folder_name),
            help="Select only colours that have staged images mapped by filename.",
        ):
            if mapped_colors:
                st.session_state["selected_colours"] = list(mapped_colors)
                st.rerun()
            else:
                st.session_state["apply_mapped_colours_widget_key"] = "selected_colours"
                st.session_state["scan_mapped_colours_now"] = True
                st.rerun()

        selected_colors = st.multiselect(
            "Colours",
            colors_available,
            key="selected_colours",
        )

        if profile.get("color_size_map"):
            st.caption("Some colours have restricted size availability. Only valid combinations will be generated.")

        available_sizes_for_selected_colors = get_available_sizes_for_selected_colors(
            profile,
            selected_colors,
        )
        normalized_sizes, should_set_sizes = normalize_multiselect_values(
            st.session_state.get("selected_sizes", []),
            available_sizes_for_selected_colors,
            selected_variants.get("size", available_sizes_for_selected_colors),
        )
        if should_set_sizes or "selected_sizes" not in st.session_state:
            st.session_state["selected_sizes"] = list(normalized_sizes)
        selected_sizes = st.multiselect(
            "Sizes",
            available_sizes_for_selected_colors,
            key="selected_sizes",
        )

        selected_variants = {
            "color": selected_colors,
            "size": selected_sizes,
        }

    st.subheader("SKU setup")
    default_sku_decoration_code = get_default_sku_decoration_code(profile, listing_memory)
    if "sku_decoration_choice" not in st.session_state:
        st.session_state["sku_decoration_choice"] = (
            default_sku_decoration_code
            if default_sku_decoration_code in SKU_DECORATION_OPTIONS
            else "Custom"
        )
    if "custom_sku_decoration_code" not in st.session_state:
        st.session_state["custom_sku_decoration_code"] = (
            ""
            if default_sku_decoration_code in SKU_DECORATION_OPTIONS
            else default_sku_decoration_code
        )

    sku_decoration_choice = st.selectbox(
        "Decoration code",
        SKU_DECORATION_OPTIONS,
        key="sku_decoration_choice",
    )
    if sku_decoration_choice == "Custom":
        custom_sku_decoration_code = st.text_input(
            "Custom decoration code",
            key="custom_sku_decoration_code",
        )
        sku_decoration_code = sanitize_sku(custom_sku_decoration_code).upper()
        if not sku_decoration_code:
            st.warning("Enter a custom SKU decoration code.")
    else:
        sku_decoration_code = sku_decoration_choice

    generated_sku_listing_code = get_or_create_generated_sku_listing_code(listing_memory)
    manual_sku_listing_code = st.text_input(
        "Listing/design code (optional)",
        key="manual_sku_listing_code",
        placeholder=generated_sku_listing_code,
        help="Leave blank to use the generated unique design identifier.",
    )
    manual_sku_listing_code = sanitize_sku(manual_sku_listing_code).upper()
    generated_sku_listing_code = sanitize_sku(generated_sku_listing_code).upper()
    sku_listing_code = manual_sku_listing_code or generated_sku_listing_code
    parent_sku_for_listing = build_parent_sku_from_context(
        profile,
        sku_decoration_code,
        sku_listing_code,
    )
    if manual_sku_listing_code:
        st.caption(f"Parent SKU: `{parent_sku_for_listing}`")
    else:
        st.caption(f"Generated listing code: `{generated_sku_listing_code}`")
        st.caption(f"Parent SKU: `{parent_sku_for_listing}`")

    with st.expander("Selected combinations preview", expanded=False):
        render_variant_combinations_preview(
            profile=profile,
            parent_sku=parent_sku_for_listing,
            selected_variants=selected_variants,
            base_title=title,
            sku_decoration_code=sku_decoration_code,
            sku_listing_code=sku_listing_code,
        )

    price_dimension_values = selected_variants.get("size", ["default"])
    size_price_map = build_size_price_inputs(
        price_dimension_values,
        saved_prices=listing_memory.get("size_price_map", {}),
        profile=profile,
        selected_variants=selected_variants,
    )
    st.session_state["current_size_price_map"] = dict(size_price_map)

    st.subheader("Inventory setup")
    quantity = st.number_input(
        "Quantity for all child variants",
        min_value=1,
        step=1,
        key="variant_quantity",
    )
    st.selectbox(
        "Content prepared by",
        WORKFLOW_ASSIGNEES,
        key="content_prepared_by",
    )

    st.caption("Check listing score to review quality before submitting the folder for review.")
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        score_clicked = st.button("Check listing score", width="stretch")
    with btn_col2:
        ready_clicked = st.button("Submit for Review", width="stretch")
    content_debug_container = st.container()
    content_preflight_container = st.container()
    content_action_result_container = st.container()

    return {
        "title": title,
        "bullets": bullets,
        "product_description": product_description,
        "generic_keywords": generic_keywords,
        "handling_time_days": handling_time_days,
        "selected_variants": selected_variants,
        "sku_decoration_code": sku_decoration_code,
        "manual_sku_listing_code": manual_sku_listing_code,
        "generated_sku_listing_code": generated_sku_listing_code,
        "sku_listing_code": sku_listing_code,
        "parent_sku_for_listing": parent_sku_for_listing,
        "size_price_map": size_price_map,
        "quantity": quantity,
        "score_clicked": score_clicked,
        "ready_clicked": ready_clicked,
        "content_debug_container": content_debug_container,
        "content_preflight_container": content_preflight_container,
        "content_action_result_container": content_action_result_container,
    }
