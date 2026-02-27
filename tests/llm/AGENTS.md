<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# llm

## Purpose
Tests for LLM integration layer: client, translation, extraction, OCR.

## Key Files
| File | Description |
|------|-------------|
| test_llm_client.py | LLM client initialization and communication |
| test_translator.py | Translation pipeline and batching |
| test_extractor.py | Content extraction from LLM responses |
| test_summarizor.py | Context summarization |
| test_reviewer.py | Translation review and validation |
| test_glossary_translator.py | Glossary term translation |
| test_ocr.py | Optical character recognition |
| test_gemini_backend.py | Google Gemini API backend |
| test_gemini_batch_gateway.py | Gemini batch processing gateway |
| test_image_token_usage.py | Image token counting and usage tracking |
| test_token_tracker.py | Token usage tracking and limits |
| test_token_usage_extraction.py | Token usage extraction from responses |
| test_language_detector.py | Language detection |
| test_session_trace.py | Session tracing and debugging |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)

<!-- MANUAL: -->
