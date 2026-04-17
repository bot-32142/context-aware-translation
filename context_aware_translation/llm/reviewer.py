from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.config import ReviewConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.cjk_normalize import build_normalized_key_mapping
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

if TYPE_CHECKING:
    from context_aware_translation.storage.schema.book_db import TermRecord

logger = logging.getLogger(__name__)


async def review_batch(
    terms: list[TermRecord],
    llm_client: LLMClient,
    config: ReviewConfig,
    source_language: str,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, list[str]]:
    """
    Review a batch of terms and classify them into 'keep' or 'ignore'.
    Returns a dictionary with keys "keep" and "ignore", each containing a list of term keys.
    """
    if not terms:
        return {"keep": [], "ignore": []}

    with llm_session_scope() as session_id:
        system_prompt = """You are a Terminology Editor for a translation project.
Your task is to review a list of extracted terms and identify which ones should be kept for the glossary and which should be ignored (noise).

Criteria for 'ignore' (Invalid Terms):
1.  **Common Words/Phrases**: Ordinary words that are not specific terminology (e.g., "suddenly", "next day", "beautiful"). Note that some common words is actually important terminology in certain contexts, so use judgment based on descriptions.
2.  **Partial Extraction**: Fragments of sentences or phrases that are not complete terms (e.g., "of the king", "red and").
3.  **Hallucinations**: Terms that clearly don't make sense or look like garbled text.
4.  **Verbs/Adjectives**: Unless they are specific coined terms or jargon.
5.  **Redundant Phrases**: If a term is merely a longer phrase containing another valid term in this list without adding specific meaning (e.g., "cast Fireball" when "Fireball" is present), ignore the phrase.

Criteria for 'keep':
1.  **Proper Nouns**: Names of people, places, organizations.
2.  **Specific Terminology**: Jargon, magical items, sci-fi concepts, skills, titles.
3.  **Consistent Entities**: Terms that appear to be significant objects or concepts based on descriptions.
4.  **Common terms**: Some common words could be translated into multiple different words in the target language, and the choice depends on the context. If the term is a common word but has multiple possible translations, it may be worth keeping to ensure consistent translation across the book.
5.  **Can't decide**: Any term that is too ambiguious to decide whether it should be ignored.

Output Format:
Return a JSON object with two keys: "keep" and "ignore".
{
  "keep": ["term1", "term3"],
  "ignore": ["term2"]
}
Ensure EVERY input term is categorized into exactly one of these lists.
"""

        # Prepare input list
        input_items = []
        for term in terms:
            description = " ".join(list(set(term.descriptions.values()))[:3])
            occurrences = sum(term.occurrence.values()) if term.occurrence else 0
            input_items.append(
                {
                    "term": term.key,
                    "occurrences": occurrences,
                    "description": description,
                }
            )

        user_prompt = f"""Review the following list of terms extracted from a {source_language} text.

Terms to Review:
{json.dumps(input_items, ensure_ascii=False, indent=2)}

Respond ONLY with the JSON object classifying these terms.
"""

        input_keys = {t.key for t in terms}
        last_error: Exception | None = None

        initial_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        messages = list(initial_messages)

        for attempt in range(3):
            raise_if_cancelled(cancel_check)
            try:
                response = await llm_client.chat(
                    list(messages),
                    config,
                    response_format={"type": "json_object"},
                    cancel_check=cancel_check,
                )
                raw_response = clean_llm_response(response)
                result = json.loads(raw_response)

                keep_list = result.get("keep", [])
                ignore_list = result.get("ignore", [])

                # Remap CJK variant keys from LLM back to expected keys
                llm_all = set(keep_list) | set(ignore_list)
                key_map = build_normalized_key_mapping(llm_all, input_keys)
                llm_to_expected = {v: k for k, v in key_map.items()}
                keep_list = [llm_to_expected.get(k, k) for k in keep_list]
                ignore_list = [llm_to_expected.get(k, k) for k in ignore_list]

                keep_set = set(keep_list)
                ignore_set = set(ignore_list)

                if not keep_set.isdisjoint(ignore_set):
                    intersection = keep_set & ignore_set
                    raise ValueError(f"Terms found in both lists: {intersection}")

                processed_keys = keep_set | ignore_set
                if processed_keys != input_keys:
                    missing = input_keys - processed_keys
                    extra = processed_keys - input_keys
                    error_msg = []
                    if missing:
                        error_msg.append(f"Missing terms: {missing}")
                    if extra:
                        error_msg.append(f"Extra terms: {extra}")
                    raise ValueError("; ".join(error_msg))

                if len(keep_list) != len(keep_set) or len(ignore_list) != len(ignore_set):
                    raise ValueError("Output lists contain duplicates")

                return {"keep": keep_list, "ignore": ignore_list}

            except ValueError as e:
                # Conversational retry for validation errors
                messages.append({"role": "assistant", "content": raw_response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response had an error: {e}. "
                            "Please correct it and return the complete JSON response again. "
                            "Follow exactly the same format and return JSON only."
                        ),
                    }
                )
                logger.warning("[llm_session=%s] Review attempt %s failed (validation): %s", session_id, attempt + 1, e)
                last_error = e
            except json.JSONDecodeError as e:
                # Fresh start — no valid response to reference
                messages = list(initial_messages)
                logger.warning(
                    "[llm_session=%s] Review attempt %s failed (JSON decode): %s", session_id, attempt + 1, e
                )
                last_error = e
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                # Fresh start for unexpected errors
                messages = list(initial_messages)
                logger.warning("[llm_session=%s] Review attempt %s failed: %s", session_id, attempt + 1, e)
                last_error = e

        raise RuntimeError(
            f"[llm_session={session_id}] All review attempts failed. Last error: {last_error}"
        ) from last_error
