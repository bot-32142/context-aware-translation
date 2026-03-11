<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# batch_jobs

## Purpose
Batch job processing for async LLM API calls, enabling cost-efficient bulk translation via vendor batch APIs. Decouples request submission (submit_batch) from result polling (poll_batch), supporting long-running background jobs with periodic status checks.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package initialization. Exports `BatchJobGateway`, `BatchPollResult`, `BatchSubmitResult`, and status constants (`POLL_STATUS_PENDING`, `POLL_STATUS_COMPLETED`, `POLL_STATUS_FAILED`, `POLL_STATUS_CANCELLED`). Also exports `GeminiBatchJobGateway` for Gemini batch API. |
| `base.py` | Abstract `BatchJobGateway` interface for provider-specific batch implementations. Methods: `build_inlined_request()`, `submit_batch()`, `poll_batch()`, `cancel_batch()`. Defines data classes: `BatchPollResult`, `BatchSubmitResult`. |
| `gemini_gateway.py` | Google Gemini batch API gateway implementing `BatchJobGateway`. Handles Gemini-specific request formatting, batch submission, polling, and result retrieval. |

## For AI Agents

### Working In This Directory

**Batch Job Lifecycle:**
1. **Build**: `build_inlined_request()` converts messages + model into provider-specific request format
2. **Submit**: `submit_batch()` sends batch to provider, returns `BatchSubmitResult` with job ID
3. **Poll**: `poll_batch(job_id)` checks job status, returns `BatchPollResult`
4. **Retrieve**: On completion, extract results from provider response
5. **Cancel**: `cancel_batch(job_id)` stops pending job

**Status Constants:**
- `POLL_STATUS_PENDING` - job still processing
- `POLL_STATUS_COMPLETED` - job finished successfully
- `POLL_STATUS_FAILED` - job failed
- `POLL_STATUS_CANCELLED` - job was cancelled

**BatchSubmitResult:**
- `batch_name` - unique identifier for the batch job (required)
- `source_file_name` - optional provider-specific source file identifier

**BatchPollResult:**
- `status` - one of the `POLL_STATUS_*` constants
- `error_text` - error message if status is FAILED
- `output_file_name` - provider-specific output file identifier (on completion)
- `warnings` - optional list of non-fatal warnings from processing

**Request Building:**
- Provider-specific implementation via `build_inlined_request()`
- Input: `messages` (chat message list), `model`, `request_kwargs` (additional parameters), `metadata` (optional)
- Output: `(request_hash, inlined_request)` tuple
  - `request_hash` - unique identifier for request deduplication
  - `inlined_request` - provider-specific request payload dict

**Gateway Pattern:**
- Subclass `BatchJobGateway` for each provider
- Implement all abstract methods for provider-specific logic
- Use `TranslatorBatchConfig` (from config.py) for batch parameters
- Store/retrieve results via `LLMBatchStore` (from storage.llm_batch_store)

**Gemini Batch API Specifics (gemini_gateway.py):**
- Uses `google-genai` SDK
- Batch format: JSONL (one request per line)
- Request IDs required for result mapping
- Supports polling with optional wait timeout
- Returns Gemini-specific response format with `candidates[]`

### Common Patterns

**Submitting a Batch:**
```python
from context_aware_translation.llm.batch_jobs import GeminiBatchJobGateway, BatchSubmitResult
from context_aware_translation.config import TranslatorBatchConfig

gateway = GeminiBatchJobGateway(api_key="...")

# Build requests
requests = [
    {"messages": [...], "model": "gemini-2.0-flash", ...},
    {"messages": [...], "model": "gemini-2.0-flash", ...},
]

# Submit batch
result: BatchSubmitResult = await gateway.submit_batch(
    batch_config=TranslatorBatchConfig(...),
    model="gemini-2.0-flash",
    inlined_requests=requests
)

print(f"Batch submitted: {result.batch_name}")
```

**Polling Batch Status:**
```python
from context_aware_translation.llm.batch_jobs import POLL_STATUS_COMPLETED, POLL_STATUS_PENDING

while True:
    poll_result = await gateway.poll_batch(job_id=result.batch_name)

    if poll_result.status == POLL_STATUS_COMPLETED:
        print(f"Batch completed: {poll_result.output_file_name}")
        break
    elif poll_result.status == POLL_STATUS_FAILED:
        print(f"Batch failed: {poll_result.error_text}")
        break
    elif poll_result.status == POLL_STATUS_PENDING:
        print("Still processing...")
        await asyncio.sleep(10)  # Check every 10 seconds
```

**Building Inlined Requests:**
```python
# For each message batch that will be translated
request_hash, inlined = gateway.build_inlined_request(
    messages=[
        {"role": "system", "content": "You are a translator"},
        {"role": "user", "content": "Translate to Chinese: ..."}
    ],
    model="gemini-2.0-flash",
    request_kwargs={"temperature": 0.3},
    metadata={"book_id": "123", "chunk_id": "456"}
)

requests.append(inlined)
```

**Error Handling:**
```python
try:
    result = await gateway.submit_batch(
        batch_config=batch_config,
        model=model,
        inlined_requests=requests
    )
except Exception as e:
    print(f"Batch submission failed: {e}")
    # Fallback to streaming API
```

## Dependencies

### Internal
- `context_aware_translation.config` - `TranslatorBatchConfig` for batch parameters
- `context_aware_translation.storage.repositories.llm_batch_store` - `LLMBatchStore` for persistence

### External
- `google-genai` (for Gemini gateway) - Google Gemini batch API client
- `openai` (future) - OpenAI batch API client (if implemented)
- `asyncio` (stdlib) - Async/await for batch operations
- `dataclasses` (stdlib) - `@dataclass` for result types

<!-- MANUAL: -->
