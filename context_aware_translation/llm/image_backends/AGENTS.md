<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# image_backends

## Purpose
Image processing backends for different LLM providers, enabling abstraction over image generation, inpainting, and enhancement APIs. Supports Google Gemini, OpenAI (DALL-E), and Alibaba Qwen for OCR, manga translation, and image reembedding workflows.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package initialization. Exports image backend factory and base classes. |
| `gemini_backend.py` | Google Gemini image generation backend. Class: `GeminiImageGenerator`. Uses google-genai SDK with per-client configuration. Supports custom base_url for endpoint compatibility. |
| `openai_backend.py` | OpenAI image generation backend (DALL-E). Class: `OpenAIImageGenerator`. Uses openai SDK with image generation and inpainting. Supports custom base_url. |
| `qwen_backend.py` | Alibaba Qwen image generation backend. Class: `QwenImageGenerator`. Uses Qwen vision models via compatible APIs. Supports custom base_url for on-premise deployments. |

## For AI Agents

### Working In This Directory

**Image Backend Interface:**
- Subclass `BaseImageGenerator` (or protocol) to implement provider
- Key methods: `generate_image()`, `inpaint_image()` for image processing
- Backend selection via factory pattern: `ImageBackend.factory(provider_name, config)`

**Provider Implementations:**

**Gemini Backend:**
- Uses `google-genai` SDK
- Per-client configuration (no global state)
- Supports custom `base_url` for private deployments
- Constructor: `GeminiImageGenerator(config: ImageReembeddingConfig)`
- Config fields: `api_key`, `model` (default: "gemini-2.0-flash-exp-image-generation"), `base_url`
- Base URL cleanup: Extracts origin only (scheme + host); google-genai appends its own `/v1beta/models/...` path

**OpenAI Backend:**
- Uses `openai` SDK (OpenAI Python client)
- Supports DALL-E 3 for generation, `dall-e-3` inpainting for text overlay
- Constructor: `OpenAIImageGenerator(config: ImageReembeddingConfig)`
- Config fields: `api_key`, `model` (default: "dall-e-3"), `base_url`
- Handles image-to-base64 encoding for API requests

**Qwen Backend:**
- Uses Alibaba Qwen vision models via compatible APIs
- Supports on-premise or cloud deployments via custom `base_url`
- Constructor: `QwenImageGenerator(config: ImageReembeddingConfig)`
- Config fields: `api_key`, `model` (default: varies), `base_url`
- Image processing via compatible API endpoints

**Configuration:**
- All backends accept `ImageReembeddingConfig` at initialization
- Config provides: `api_key`, `model`, `base_url`, `temperature`, `max_tokens`
- Base URL handling: strip trailing slashes and API version paths to avoid double-pathing

**Image Format Handling:**
- Input: bytes (PNG, JPEG, etc.)
- Output: bytes (PNG preferred)
- Conversions: base64 encoding for API transmission, PIL for local processing
- Preserve transparency and color profiles where possible

**Async Execution:**
- All methods are async (`async def`) using `asyncio`
- Supports concurrent image processing via `asyncio.gather()`
- Timeout handling at LLM client level (see `llm/client.py`)

**Usage Patterns:**

**Image Generation (create new image):**
```python
from context_aware_translation.llm.image_backends.gemini_backend import GeminiImageGenerator
from context_aware_translation.config import ImageReembeddingConfig

config = ImageReembeddingConfig(
    api_key="...",
    model="gemini-2.0-flash-exp-image-generation",
    base_url=None  # Use default
)

backend = GeminiImageGenerator(config)
image_bytes = await backend.generate_image(
    prompt="A book cover with translated Chinese text",
    width=800,
    height=600
)
```

**Image Inpainting (overlay text on image):**
```python
# Use OpenAI backend for text overlay
from context_aware_translation.llm.image_backends.openai_backend import OpenAIImageGenerator

backend = OpenAIImageGenerator(config)
inpainted = await backend.inpaint_image(
    image=source_image_bytes,
    mask=mask_bytes,  # Optional mask for target region
    prompt="Translate manga text to English, keep original style"
)
```

**Backend Factory:**
```python
from context_aware_translation.llm.image_backends import create_backend

backend = await create_backend(
    provider="gemini",
    config=ImageReembeddingConfig(...)
)

# Or manual selection
if provider_name == "gemini":
    backend = GeminiImageGenerator(config)
elif provider_name == "openai":
    backend = OpenAIImageGenerator(config)
elif provider_name == "qwen":
    backend = QwenImageGenerator(config)
```

**Error Handling:**
```python
from context_aware_translation.llm.client import LLMError

try:
    image = await backend.generate_image(prompt, width, height)
except LLMError as e:
    # Handle LLM errors (auth, rate limit, etc.)
    logger.error(f"Image generation failed: {e}")
```

### Common Patterns

**Manga Text Inpainting Workflow:**
```python
from pathlib import Path

# 1. Read manga panel image
panel_bytes = Path("panel.png").read_bytes()

# 2. Use OpenAI for text overlay (best for manga)
backend = OpenAIImageGenerator(config)

# 3. Generate mask (region with text to replace)
mask = create_mask_for_text_region(panel_bytes)  # External function

# 4. Inpaint with translated text
translated_panel = await backend.inpaint_image(
    image=panel_bytes,
    mask=mask,
    prompt="Replace Japanese text with English translation, maintain manga style"
)

# 5. Save result
Path("panel_translated.png").write_bytes(translated_panel)
```

**Provider Failover:**
```python
backends = {
    "primary": GeminiImageGenerator(config),
    "fallback": OpenAIImageGenerator(fallback_config)
}

try:
    image = await backends["primary"].generate_image(...)
except LLMError:
    logger.warning("Primary backend failed, trying fallback")
    image = await backends["fallback"].generate_image(...)
```

**Batch Image Processing:**
```python
import asyncio

images = [...]  # List of image bytes

tasks = [
    backend.generate_image(prompt, width, height)
    for prompt in prompts
]

results = await asyncio.gather(*tasks, return_exceptions=True)
```

## Dependencies

### Internal
- `context_aware_translation.config` - `ImageReembeddingConfig` for backend configuration
- `context_aware_translation.llm.image_generator` - `BaseImageGenerator` interface
- `context_aware_translation.llm.client` - LLM error types for exception handling

### External
- `google-genai` (Gemini) - Google Gemini image generation SDK
- `openai` (OpenAI) - OpenAI API client for DALL-E
- `requests` or compatible HTTP client (Qwen) - HTTP communication
- `pillow` (PIL) - Image format conversion and encoding
- `base64` (stdlib) - Base64 encoding for API transmission
- `asyncio` (stdlib) - Async/await framework

<!-- MANUAL: -->
