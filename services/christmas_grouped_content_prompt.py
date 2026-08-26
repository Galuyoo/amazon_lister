from __future__ import annotations

from pathlib import Path
from string import Template


CANONICAL_GROUPED_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "christmas_grouped_listing_content_chatgpt_prompt.txt"
)


def load_christmas_grouped_content_prompt(
    prompt_path: Path | None = None,
) -> str:
    return (prompt_path or CANONICAL_GROUPED_PROMPT_PATH).read_text(encoding="utf-8")


def render_christmas_grouped_content_prompt(
    mpn: str,
    optional_notes: str = "",
    output_filename: str = "",
    prompt_path: Path | None = None,
) -> str:
    template = Template(load_christmas_grouped_content_prompt(prompt_path))
    normalized_mpn = str(mpn or "").strip()
    return template.substitute(
        MPN=normalized_mpn or "Not available",
        OPTIONAL_NOTES=str(optional_notes or "").strip() or "None provided",
        OUTPUT_FILENAME=(
            str(output_filename or "").strip()
            or (
                f"{normalized_mpn}_christmas_grouped_listing_content.json"
                if normalized_mpn
                else "christmas_grouped_listing_content.json"
            )
        ),
    )
