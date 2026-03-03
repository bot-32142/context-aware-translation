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
    extracted_texts: list[str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Translate manga pages using vision LLM.

    Sends page images + glossary terms to LLM. Returns translated text per page.
    """
    with llm_session_scope() as session_id:
        num_pages = len(page_images)
        if num_pages != 1:
            raise ValueError(f"Manga translation requires exactly 1 page per call, got {num_pages}")
        if extracted_texts is None:
            raise ValueError("Manga translation requires extracted_texts for strict line mapping")
        if len(extracted_texts) != num_pages:
            raise ValueError(f"Expected {num_pages} extracted text entries, got {len(extracted_texts)}")

        # Build glossary section
        glossary_items = []
        for name, translated_name, description in terms:
            entry: dict[str, str] = {"term": name, "translation": translated_name}
            if description:
                entry["context"] = description
            glossary_items.append(entry)
        source_text = extracted_texts[0].replace("\r\n", "\n").replace("\r", "\n")
        source_lines = [] if source_text == "" else source_text.split("\n")
        payload_json = json.dumps(
            {
                "glossary": glossary_items,
                "source_lines": source_lines,
            },
            ensure_ascii=False,
            indent=2,
        )

        system_prompt = f"""You are a professional manga translator. Translate from {source_language} to {target_language}.

Use the manga page image only as context for tone, scene, and OCR ambiguity.
Use extracted source lines as the single source of truth.

Output format (strict):
Return ONLY valid JSON object:
{{"translations": ["line1", "line2", ...]}}

Rules:
1) translations length MUST equal source_lines length exactly.
2) translations[i] MUST translate source_lines[i] only.
3) Do not merge, split, reorder, or drop lines.
4) Keep empty source lines as empty strings.
5) Use glossary terms when applicable."""

        img_bytes, mime_type = page_images[0]
        b64 = base64.b64encode(img_bytes).decode("ascii")
        data_uri = f"data:{mime_type};base64,{b64}"
        user_content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {
                "type": "text",
                "text": payload_json,
            },
        ]

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
                if isinstance(parsed, dict) and isinstance(parsed.get("translations"), list):
                    translations = parsed["translations"]
                else:
                    raise ValueError(f"Expected JSON object with translations list, got {type(parsed).__name__}")

                if len(translations) != len(source_lines):
                    raise ValueError(f"Expected {len(source_lines)} line translations, got {len(translations)}")
                translated_lines = [str(item) for item in translations]
                return ["\n".join(translated_lines)]
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
        raise ValueError(f"[llm_session={session_id}] Failed to translate manga page after {attempts} attempts")
