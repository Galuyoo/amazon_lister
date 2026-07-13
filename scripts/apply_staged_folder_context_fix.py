from __future__ import annotations

from pathlib import Path
import shutil


APP_PATH = Path("app.py")
BACKUP_PATH = Path("app_before_staged_folder_context_fix.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {label} anchor, found {count}. "
            "The app may already be patched or may have changed."
        )
    return text.replace(old, new, 1)


def main() -> None:
    if not APP_PATH.exists():
        raise FileNotFoundError("Run this script from the repository root; app.py was not found.")

    text = APP_PATH.read_text(encoding="utf-8")
    shutil.copy2(APP_PATH, BACKUP_PATH)

    text = replace_once(
        text,
        '''    pending_staged_folder_selection = st.session_state.pop("pending_staged_folder_selection_on_rerun", None)
    if pending_staged_folder_selection:
        st.session_state["staged_folder_select"] = pending_staged_folder_selection
        st.session_state.pop("last_detected_template_folder", None)
''',
        '''    pending_staged_folder_selection = st.session_state.pop("pending_staged_folder_selection_on_rerun", None)
    if pending_staged_folder_selection:
        st.session_state["staged_folder_select"] = pending_staged_folder_selection
        st.session_state["active_staged_folder_context"] = pending_staged_folder_selection
        st.session_state.pop("last_detected_template_folder", None)
''',
        "pending staged-folder selection",
    )

    text = replace_once(
        text,
        '''    if st.session_state.pop("clear_staged_folder_selection_on_rerun", False):
        st.session_state["staged_folder_select"] = None
        st.session_state.pop("last_detected_template_folder", None)
''',
        '''    if st.session_state.pop("clear_staged_folder_selection_on_rerun", False):
        st.session_state["staged_folder_select"] = None
        st.session_state.pop("active_staged_folder_context", None)
        st.session_state.pop("last_detected_template_folder", None)
''',
        "clear staged-folder selection",
    )

    text = replace_once(
        text,
        '''        if active_task_folder and not st.session_state.get("staged_folder_select"):
            st.session_state["folder_source_mode"] = "Use staged folder"
            st.session_state["staged_folder_select"] = active_task_folder
''',
        '''        if active_task_folder and not st.session_state.get("staged_folder_select"):
            st.session_state["folder_source_mode"] = "Use staged folder"
            st.session_state["staged_folder_select"] = active_task_folder
            st.session_state["active_staged_folder_context"] = active_task_folder
''',
        "active task staged-folder restoration",
    )

    text = replace_once(
        text,
        '''    folder_source = st.session_state.get("folder_source_mode", "Use staged folder")
    initial_staged_folder_name = st.session_state.get("staged_folder_select", "") if folder_source == "Use staged folder" else ""
    listing_memory: dict[str, Any] = {}
''',
        '''    folder_source = st.session_state.get("folder_source_mode", "Use staged folder")
    selected_staged_folder = str(st.session_state.get("staged_folder_select", "") or "").strip()
    remembered_staged_folder = str(st.session_state.get("active_staged_folder_context", "") or "").strip()
    if selected_staged_folder:
        remembered_staged_folder = selected_staged_folder
        st.session_state["active_staged_folder_context"] = selected_staged_folder
    initial_staged_folder_name = (
        selected_staged_folder or remembered_staged_folder
        if folder_source == "Use staged folder"
        else ""
    )
    listing_memory: dict[str, Any] = {}
''',
        "initial staged-folder context",
    )

    text = replace_once(
        text,
        '''    current_folder_source_mode = st.session_state.get("folder_source_mode", "Use staged folder")
    current_detect_folder = st.session_state.get("staged_folder_select", "") if current_folder_source_mode == "Use staged folder" else ""
''',
        '''    current_folder_source_mode = st.session_state.get("folder_source_mode", "Use staged folder")
    current_detect_folder = initial_staged_folder_name if current_folder_source_mode == "Use staged folder" else ""
''',
        "template detection staged-folder context",
    )

    text = replace_once(
        text,
        '''                    staged_folder_name = st.selectbox(
                        "Dropbox folder",
                        staged_folder_names,
                        index=None,
                        placeholder="Select a staged folder",
                        key="staged_folder_select",
                    )
''',
        '''                    staged_folder_name = st.selectbox(
                        "Dropbox folder",
                        staged_folder_names,
                        index=None,
                        placeholder="Select a staged folder",
                        key="staged_folder_select",
                    )
                    if staged_folder_name:
                        st.session_state["active_staged_folder_context"] = staged_folder_name
''',
        "staged-folder selectbox",
    )

    text = replace_once(
        text,
        '''    folder_source = st.session_state.get("folder_source_mode", folder_source)
    if folder_source == "Use staged folder":
        staged_folder_name = st.session_state.get("staged_folder_select") or active_staged_folder_name
''',
        '''    folder_source = st.session_state.get("folder_source_mode", folder_source)
    if folder_source == "Use staged folder":
        staged_folder_name = (
            st.session_state.get("staged_folder_select")
            or st.session_state.get("active_staged_folder_context")
            or active_staged_folder_name
        )
''',
        "active staged-folder fallback",
    )

    APP_PATH.write_text(text, encoding="utf-8")
    print(f"Patched {APP_PATH} successfully.")
    print(f"Backup written to {BACKUP_PATH}.")


if __name__ == "__main__":
    main()
