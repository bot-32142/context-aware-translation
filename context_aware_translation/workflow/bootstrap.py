from typing import cast

from transformers import PreTrainedTokenizer

from context_aware_translation.config import Config, WorkflowRuntimeConfig
from context_aware_translation.core.context_extractor import TermExtractor
from context_aware_translation.core.context_manager import TranslationContextManager, TranslationContextManagerAdapter
from context_aware_translation.core.manga_document_handler import MangaDocumentHandler
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.translation_strategies import (
    LLMChunkTranslator,
    LLMGlossaryTranslator,
    LLMMangaPageTranslator,
    LLMSourceLanguageDetector,
    LLMTermMemoryUpdater,
    LLMTermReviewer,
)
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.repositories.term_repository import TermRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.utils.chunking import get_tokenizer
from context_aware_translation.workflow.image_fetcher import RepoImageFetcher
from context_aware_translation.workflow.runtime import WorkflowContext


def _build_llm_client(runtime_config: WorkflowRuntimeConfig) -> LLMClient:
    return LLMClient(runtime_config.summarizor_config)


def _build_manager(
    runtime_config: WorkflowRuntimeConfig,
    llm_client: LLMClient,
    db: SQLiteBookDB,
    document_repo: DocumentRepository,
) -> TranslationContextManagerAdapter:
    term_repo = TermRepository(db)

    review_config = runtime_config.review_config
    term_reviewer = LLMTermReviewer(llm_client, review_config) if review_config is not None else None

    translator_config = runtime_config.translator_config
    translator_model = translator_config.model
    if translator_model is None:
        raise ValueError("translator_config.model must be set")

    tokenizer = cast(PreTrainedTokenizer, get_tokenizer(translator_model))
    term_extractor = TermExtractor(llm_client, runtime_config.extractor_config)
    language_detector = LLMSourceLanguageDetector(llm_client, runtime_config.extractor_config)
    glossary_translator = LLMGlossaryTranslator(
        runtime_config.glossary_config,
        runtime_config.translation_target_language,
        llm_client,
    )
    chunk_translator = LLMChunkTranslator(
        llm_client,
        translator_config,
        runtime_config.polish_config,
        runtime_config.translation_target_language,
    )
    term_memory_updater = LLMTermMemoryUpdater(
        runtime_config.summarizor_config,
        llm_client,
    )

    base_manager = TranslationContextManager(
        term_repo,
        term_extractor,
        tokenizer,
        source_language_detector=language_detector,
        glossary_translator=glossary_translator,
        chunk_translator=chunk_translator,
        term_reviewer=term_reviewer,
        term_memory_updater=term_memory_updater,
        max_term_description_length=runtime_config.summarizor_config.max_term_description_length,
        target_language=runtime_config.translation_target_language,
    )
    manager = TranslationContextManagerAdapter(base_manager)

    manga_config = runtime_config.manga_translator_config
    if manga_config is not None:
        manga_translator = LLMMangaPageTranslator(
            llm_client,
            manga_config,
            runtime_config.translation_target_language,
        )
        manga_handler = MangaDocumentHandler(
            manga_page_translator=manga_translator,
            image_fetcher=RepoImageFetcher(document_repo),
            concurrency=manga_config.concurrency,
        )
        manager.register_handler("manga", manga_handler)

    return manager


def build_workflow_runtime(
    config: Config,
    runtime_config: WorkflowRuntimeConfig,
    *,
    book_id: str | None = None,
) -> WorkflowContext:
    """Build all runtime dependencies required for workflow execution."""
    llm_client = _build_llm_client(runtime_config)
    db = SQLiteBookDB(runtime_config.sqlite_path)
    document_repo = DocumentRepository(db)
    manager = _build_manager(runtime_config, llm_client, db, document_repo)

    return WorkflowContext(
        config=config,
        llm_client=llm_client,
        manager=manager,
        db=db,
        document_repo=document_repo,
        book_id=book_id,
    )
