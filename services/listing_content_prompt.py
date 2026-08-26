from pathlib import Path
from string import Template


CANONICAL_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "amazon_listing_content_chatgpt_prompt.txt"
)


def load_amazon_listing_content_prompt(prompt_path: Path | None = None) -> str:
    return (prompt_path or CANONICAL_PROMPT_PATH).read_text(encoding="utf-8")


def render_amazon_listing_content_prompt(
    mpn: str = "",
    optional_notes: str = "",
    output_filename: str = "amazon_listing_content.json",
    prompt_path: Path | None = None,
) -> str:
    template = Template(load_amazon_listing_content_prompt(prompt_path))
    return template.substitute(
        MPN=str(mpn or "").strip() or "Not available",
        OPTIONAL_NOTES=str(optional_notes or "").strip() or "None provided",
        OUTPUT_FILENAME=str(output_filename or "").strip() or "amazon_listing_content.json",
    )
