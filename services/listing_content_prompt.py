from pathlib import Path


CANONICAL_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "amazon_listing_content_chatgpt_prompt.txt"
)


def load_amazon_listing_content_prompt(prompt_path: Path | None = None) -> str:
    return (prompt_path or CANONICAL_PROMPT_PATH).read_text(encoding="utf-8")
