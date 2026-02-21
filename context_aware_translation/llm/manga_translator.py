from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import Any

from context_aware_translation.config import MangaTranslatorConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


async def translate_manga_pages(
    page_images: list[tuple[bytes, str]],
    terms: list[tuple[str, str, str]],
    llm_client: LLMClient,
    manga_config: MangaTranslatorConfig,
    source_language: str,
    target_language: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Translate manga pages using vision LLM.

    Sends page images + glossary terms to LLM. Returns translated text per page.
    """
    with llm_session_scope() as session_id:
        num_pages = len(page_images)
        system_prompt = f"""You are a professional manga translator. Translate all visible text in the provided manga pages from {source_language} to {target_language}.

Use the glossary below for consistent term translation.
Output a JSON array with exactly {num_pages} element(s), one per page in the same order as the input.
Each element is a string containing all translated text for that page.
If a page has no text, use an empty string.
Example for 2 pages: ["translated text page 1", "translated text page 2"]
Return ONLY the JSON array."""

        # Build glossary section
        glossary_items = []
        for name, translated_name, description in terms:
            entry: dict[str, str] = {"term": name, "translation": translated_name}
            if description:
                entry["context"] = description
            glossary_items.append(entry)

        # Build user content with images
        user_content: list[dict[str, Any]] = []
        for img_bytes, mime_type in page_images:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            data_uri = f"data:{mime_type};base64,{b64}"
            user_content.append({"type": "image_url", "image_url": {"url": data_uri}})

        glossary_text = json.dumps(glossary_items, ensure_ascii=False, indent=2) if glossary_items else "[]"
        user_content.append(
            {
                "type": "text",
                "text": f"Glossary:\n{glossary_text}\n\nTranslate all text in the {len(page_images)} manga page(s) above.",
            }
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        attempts = manga_config.max_retries + 1
        for attempt in range(attempts):
            raise_if_cancelled(cancel_check)
            try:
                response = await llm_client.chat(
                    messages=messages,
                    step_config=manga_config,
                    cancel_check=cancel_check,
                )
                response = clean_llm_response(response)
                parsed = json.loads(response)
                if isinstance(parsed, list):
                    translations = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get("translations"), list):
                    translations = parsed["translations"]
                else:
                    raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")
                if len(translations) != len(page_images):
                    raise ValueError(f"Expected {len(page_images)} translations, got {len(translations)}")
                return [str(t) for t in translations]
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                logger.warning(
                    "[llm_session=%s] Manga translation attempt %s/%s failed: %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                if attempt >= attempts - 1:
                    raise
        raise ValueError(f"[llm_session={session_id}] Failed to translate manga pages after {attempts} attempts")
