<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# llm

## Purpose
LLM integration layer handling all AI API interactions including translation, extraction, summarization, OCR, and token tracking. Centralizes OpenAI/Gemini client logic with retry/rate-limiting, supports multi-pass glossary extraction, image generation, and manga-specific OCR. Uses tenacity for exponential backoff retry strategies.

## Key Files

| File | Description |
|------|-------------|
| `client.py` | Central OpenAI/API client with retry logic (tenacity), timeout handling, rate-limit recovery, and session tracing. Single source of truth for LLM API configuration and error handling. |
| `translator.py` | LLM-powered translation of document chunks using configurable prompts and context injection. Validates LLM response schema and coverage. |
| `extractor.py` | Multi-pass glossary term gleaning via LLM. Implements `TUPLE_DELIMITER` and `COMPLETION_DELIMITER` parsing for term extraction from chunks. |
| `summarizor.py` | Hierarchical context summarization for LSM-tree-like token compression. Reduces context size while preserving relevance. |
| `reviewer.py` | Translation quality review and scoring via LLM. Reviews translated chunks for consistency and accuracy. |
| `glossary_translator.py` | Specialized LLM translator for glossary terms. Handles term definition translation independent of document content. |
| `language_detector.py` | Language detection for documents and content. Determines source/target language for downstream processing. |
| `ocr.py` | LLM-based OCR for scanned documents and images. Falls back to vision-capable models (GPT-4V, Gemini). |
| `manga_ocr.py` | Manga-specific OCR leveraging LLM for comic text extraction with layout awareness. |
| `epub_ocr.py` | EPUB-specific OCR handling for embedded images in e-books. |
| `manga_translator.py` | Specialized image translation for manga panels. Inpaints translated text into manga images. |
| `image_generator.py` | Image generation backend supporting DALL-E, Gemini, and Qwen. Used for inpainting and image synthesis. |
| `token_tracker.py` | Tracks and reports LLM token usage (input/output) for cost monitoring and quota enforcement. |
| `session_trace.py` | Session-based request tracing for debugging and audit logs. Provides `llm_session_scope()` context manager. |
| `translation_strategies.py` | Strategy patterns for LLM translation (chunking, batch size, retry behavior). Pluggable translation logic. |

## Subdirectories (if any)

| Directory | Purpose |
|-----------|---------|
| `batch_jobs/` | Batch job processing for async API calls (e.g., OpenAI batch API). Decouples request submission from result polling. |
| `image_backends/` | Image processing and generation backends: `openai_backend.py` (DALL-E), `gemini_backend.py` (Gemini), `qwen_backend.py` (Alibaba Qwen), `base.py` (interface). |

## For AI Agents

### Working In This Directory

**Client Integration:**
- `client.py` is the single source of truth for LLM API calls
- All LLM interactions must route through `LLMClient` (no direct OpenAI imports elsewhere)
- Tenacity retry decorators handle transient failures with exponential backoff
- Rate-limit errors (`RateLimitError`) are caught and converted to `LLMRateLimitError`
- Timeout errors (`APITimeoutError`) are caught and converted to `LLMTimeoutError`
- Authentication errors (`APIConnectionError` for auth) are caught and converted to `LLMAuthError`

**Critical Configuration:**
- `num_of_chunks_per_llm_call` in `TranslatorConfig` must NOT exceed 10 (causes hallucinations; default 5)
- Each file that calls LLM APIs (translator, extractor, etc.) accepts an `LLMConfig` subclass parameter
- Session tracing via `llm_session_scope()` for audit trails and debugging

**Multi-Pass Extraction:**
- `extractor.py` implements multi-pass gleaning (default 3 passes) for glossary terms
- Each pass refines term extraction with context from prior passes
- Terms are validated via `is_valid_term()` before insertion into storage

**Async Execution:**
- Most LLM functions are async (`async def`) using `asyncio` coroutines
- Batch operations via `asyncio.gather()` respect `concurrency` limits
- Cancellation via `OperationCancelledError` is raised and propagated

**Image Processing:**
- Image backends are pluggable via `image_backends/base.py` interface
- `manga_translator.py` uses image inpainting backends to overlay translated text
- `ocr.py` and `manga_ocr.py` leverage vision-capable models (GPT-4V, Gemini Vision)

**Token Tracking:**
- `token_tracker.py` accumulates input/output tokens per endpoint profile
- Token counts are persisted in `EndpointProfile.tokens_used`
- Enable/disable token limits via `EndpointProfile.token_limit`

### Common Patterns

**Error Handling in LLM Calls:**
```python
from context_aware_translation.llm.client import LLMClient, LLMError, LLMRateLimitError, LLMTimeoutError

try:
    result = await client.call_api(...)
except LLMRateLimitError:
    # Backoff and retry (tenacity handles automatically)
    pass
except LLMTimeoutError:
    # Handle timeout (may retry at caller level)
    pass
except LLMError as e:
    # Generic LLM failure
    pass
```

**Session Tracing:**
```python
from context_aware_translation.llm.session_trace import llm_session_scope, get_llm_session_id

with llm_session_scope(session_id="my-task-123"):
    # All LLM calls within this scope are tagged with session_id
    result = await translator.translate(chunks, config)
```

**Config Reference via EndpointProfile:**
```python
# TranslatorConfig can reference an EndpointProfile by name
translator_config = TranslatorConfig(
    endpoint_profile_name="gpt4-production",  # Resolved to EndpointProfile at runtime
    ...
)
```

**Batch Job Submission:**
```python
from context_aware_translation.llm.batch_jobs.base import submit_batch_job

job_id = await submit_batch_job(requests, endpoint_profile)
# Poll results later via retrieve_batch_job()
```

**Image Backend Abstraction:**
```python
from context_aware_translation.llm.image_backends.base import ImageBackend

backend = ImageBackend.factory(backend_name="openai")
inpainted = await backend.inpaint_image(image, translations)
```

## Dependencies

### Internal
- `context_aware_translation.config` - `LLMConfig`, `TranslatorConfig`, `ExtractorConfig`, etc.; `EndpointProfile`
- `context_aware_translation.core.models` - `Term` and related data models
- `context_aware_translation.storage.book_db` - `ChunkRecord` for extraction context
- `context_aware_translation.utils.*` - text/image processing utilities, JSON cleaning, compression markers
- `context_aware_translation.documents.*` - document type handling for OCR/inpainting

### External
- `openai` - OpenAI API client (chat completion, vision, batch API)
- `google-genai` - Google Gemini API client
- `tenacity` - Retry logic with exponential backoff
- `asyncio` - Async execution framework
- `pillow` - Image processing for OCR and inpainting
- `torch`, `transformers` - ML model inference (optional, used in some backends)
- `platformdirs` - Platform-specific directory handling

<!-- MANUAL: -->
