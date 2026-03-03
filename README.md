**English** | [中文](README_ZH.md)

# Context-Aware Translation (CAT)

CAT is a desktop translation tool for long-form text and various document types (books, PDFs, EPUBs, manga, scanned pages), with a focus on terminology consistency and cross-document context.

## Why CAT

- Automatically extracts terms and their descriptions from source material to build a usable glossary.
- Each term accumulates context in import order; relevant descriptions are injected during translation.
- Ensures consistent translations for related terms.
- Preserves original structure/layout where supported (e.g., EPUB structure, text line-to-line mapping).
- One pipeline covers text, EPUB, PDF, scanned images, and manga.
- Supports OCR with manual review before export.
- Supports image text embedding.

## Disclaimer

**As an individual, I'm unable to extensively test different languages, models, and formats. You will most likely see bugs. Please report to help.**
**This entire project is vibe-coded and I only reviewed critial pieces of code + ai review/summary, and manually tested.**

## Core Idea: Context Management

CAT does not translate each chunk as isolated text.

1. Import and split documents in reading order.
2. Automatically extract terms and build occurrence mappings.
3. Use a context tree to continuously summarize term descriptions.
4. During translation, inject only relevant terms for the current batch (term name + translation + summarized description).

The result: better long-document consistency without sending the entire book as context every time.

## Recommended Workflow

1. **Import**: Import documents in the intended reading order.
2. **OCR Review** (if needed): Run OCR first, then correct the OCR text.
3. **Glossary**: Build/import a glossary, review and translate terms.
4. **Translate**: Translate the selected documents. It is recommended to send less for consistent high-quality output. More context will certainly lead to hallucination. Under 3000 tokens is recommended, depending on your model and whether context summaries is enabled or not.
5. **Export**: Export by document type and format.

## Supported Types

| Document Type | Import | Export | OCR Required Before Translation? |
|---|---|---|---|
| Text | Single or folder: `.txt` / `.md` | `txt` | No |
| PDF | Single `.pdf` | `epub`, `md` | Yes |
| Scanned Book | Image files/folder | `epub`, `md` | Yes |
| Manga | `.cbz` or image folder | `cbz` | Yes |
| EPUB | Single `.epub` | `epub`, `md`, `docx`, `html` | No (but supports image OCR) |

## LLM Endpoint Configuration

You can bind different endpoints/models to different steps to balance cost, speed, and quality.

| Step | Purpose | Endpoint/Model Suggestions |
|---|---|---|
| **Term Extraction** | Extract term candidates and initial descriptions from text chunks | This step processes large amounts of input. Prefer low-cost models with input caching and stable structured output (e.g., models supporting prompt cache). DeepSeek is strongly recommended. |
| **Term Description Summarization** | Summarize term descriptions across contexts to build reusable semantics | Similar to term extraction — high input volume with repetition. Prefer low-cost + strong input caching + stable long-context handling. DeepSeek is strongly recommended. |
| **Term Translation** | Translate terms consistently into the target language | Prefer models with accurate term translation and stable formatting. Cost is typically lower than body translation but consistency is key. Recommend models with broad training data coverage and reasonable pricing, such as Gemini 3 Flash. |
| **Body Translation** | Execute the main document translation | This is the most quality-sensitive step. Prefer models with high translation quality, stable style, and strong long-text performance. Gemini 2.5 Pro with low thinking is strongly recommended. Gemini 3 or other strong reasoning models tend to produce overly stilted translations. |
| **OCR** (optional) | Recognize text in images and output editable text | Requires a vision model (multimodal). Prefer models with high OCR accuracy and good adaptation to mixed layouts, vertical text, and noisy images, such as Gemini 3 Flash. |
| **Term Review** (optional) | Automated term quality review | Suited for models with strong reasoning and stable instruction-following; can be separated from body translation to control cost. |
| **Manga Translation** (optional) | Page-level manga translation (with image context) | Requires a multimodal model with strong visual comprehension and conversational tone handling. |
| **Image Text Embedding** (optional) | Re-embed translated text into images | Requires a backend supporting image editing/inpainting. Prefer models with stable layout preservation. |

Recommended practices:

1. Use a "low-cost caching model" for **Term Extraction** + **Term Description Summarization**.
2. Use a "high-quality translation model" for **Body Translation** (and optionally for **Term Translation**).
3. Bind vision-related steps (**OCR** / **Manga Translation** / **Image Text Embedding**) to separate multimodal endpoints to avoid quota and performance interference.

These recommendations are already pre-configured in the default endpoint and config profiles (except **Image Text Embedding**, which requires separate setup). You only need to fill in the API keys to get started.

## Notes
* OCR cannot handle overly complex layouts. **The OCR is not designed to keep the original layout but to render the original content in an opinioned way.**
* If a single sentence in the source text spans multiple paragraphs, formatting may break, and may result in translation failure.
* All llm responses are cached and persisted at the earliest possible time so cancellation won't result in data loss if you want to stop and resume from where you left out.
* Image edit API hallucinates badly for long texts (e.g. complicated manga page with many words) when tested using gemini-3-pro-image-preview. In other words, full-automation of manga translation would require stronger/fine-tuned model. We just need to be patient and wait for the next-gen image edit model release probably.
