from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.app_setup import ConnectionDraft, SetupWizardRequest
from context_aware_translation.application.contracts.common import ProviderKind, SurfaceStatus
from context_aware_translation.application.contracts.document import (
    ImageAssetState,
    OCRTextElement,
    RunOCRRequest,
    SaveOCRPageRequest,
)
from context_aware_translation.application.contracts.projects import CreateProjectRequest
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode
from context_aware_translation.application.events import DocumentInvalidatedEvent
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import ChunkRecord, SQLiteBookDB, TranslationChunkRecord
from context_aware_translation.workflow.tasks.handlers.image_reembedding import ImageReembeddingHandler
from context_aware_translation.workflow.tasks.handlers.ocr import OCRHandler


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def _build_configured_context(tmp_path: Path):
    context = build_application_context(library_root=tmp_path)
    context.services.app_setup.run_setup_wizard(
        SetupWizardRequest(
            providers=[ProviderKind.OPENAI],
            connections=[
                ConnectionDraft(
                    display_name="OpenAI",
                    provider=ProviderKind.OPENAI,
                    api_key="test-key",
                )
            ],
        )
    )
    return context


def _tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4//8/AwAI/AL+XJadOQAAAABJRU5ErkJggg=="
    )


def _open_repo(context, project_id: str) -> tuple[SQLiteBookDB, DocumentRepository]:
    db = SQLiteBookDB(context.runtime.book_manager.get_book_db_path(project_id))
    return db, DocumentRepository(db)


def _configure_project_for_ocr(context, project_id: str) -> None:
    endpoint = context.runtime.book_manager.create_endpoint_profile(
        name="Test OCR",
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-3-flash-preview",
    )
    config = context.runtime.get_effective_config_payload(project_id)
    for key in (
        "extractor_config",
        "summarizor_config",
        "glossary_config",
        "translator_config",
        "review_config",
        "ocr_config",
        "image_reembedding_config",
        "manga_translator_config",
    ):
        config.setdefault(key, {})
        config[key]["endpoint_profile"] = endpoint.profile_id
    context.runtime.book_manager.set_book_custom_config(project_id, config)


def _register_active_task(context, record, claims) -> None:
    context.runtime.task_engine._core._active_claims[record.task_id] = claims


def test_document_service_get_ocr_allows_current_page_rerun_after_completion(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Project", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("scanned_book")
            repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"text": "old text"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.commit()
        finally:
            db.close()

        state = context.services.document.get_ocr(project_id, document_id)

        assert len(state.pages) == 1
        assert state.pages[0].extracted_text == "old text"
        assert state.actions.save.enabled
        assert state.actions.run_current.enabled
        assert not state.actions.run_pending.enabled
        assert state.actions.run_pending.blocker is not None
    finally:
        context.close()


def test_document_service_run_ocr_allows_other_page_while_page_task_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Parallel Pages", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("scanned_book")
            current_source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            running_source_id = repo.insert_document_source(
                document_id,
                1,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            db.commit()
        finally:
            db.close()

        active_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="ocr",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [running_source_id]}),
        )
        active_payload = OCRHandler().decode_payload(active_record)
        _register_active_task(context, active_record, OCRHandler().claims(active_record, active_payload))

        submitted: dict[str, object] = {}

        def _fake_submit_and_start(task_type, book_id, **params):  # noqa: ANN001
            submitted["task_type"] = task_type
            submitted["book_id"] = book_id
            submitted["params"] = params
            return context.runtime.task_store.create(
                book_id=book_id,
                task_type=task_type,
                document_ids_json=json.dumps(params.get("document_ids")),
                payload_json=json.dumps(params, ensure_ascii=False),
            )

        monkeypatch.setattr(context.runtime.task_engine, "submit_and_start", _fake_submit_and_start, raising=True)

        state = context.services.document.get_ocr(project_id, document_id)
        result = context.services.document.run_ocr(
            RunOCRRequest(project_id=project_id, document_id=document_id, source_id=current_source_id)
        )

        assert state.pages[0].source_id == current_source_id
        assert state.pages[0].status is SurfaceStatus.READY
        assert state.pages[1].source_id == running_source_id
        assert state.pages[1].status is SurfaceStatus.RUNNING
        assert state.actions.run_current.enabled
        assert not state.actions.run_pending.enabled
        assert submitted["task_type"] == "ocr"
        assert submitted["book_id"] == project_id
        assert submitted["params"] == {"document_ids": [document_id], "source_ids": [current_source_id]}
        assert result.command_name == "ocr"
    finally:
        context.close()


def test_document_service_get_ocr_aggregates_multiple_active_tasks(
    tmp_path: Path,
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Parallel Progress", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("scanned_book")
            first_source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            second_source_id = repo.insert_document_source(
                document_id,
                1,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            db.commit()
        finally:
            db.close()

        first_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="ocr",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [first_source_id]}),
        )
        second_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="ocr",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [second_source_id]}),
        )
        first_record = context.runtime.task_store.update(first_record.task_id, completed_items=1, total_items=3)
        second_record = context.runtime.task_store.update(second_record.task_id, completed_items=2, total_items=4)
        first_payload = OCRHandler().decode_payload(first_record)
        second_payload = OCRHandler().decode_payload(second_record)
        _register_active_task(context, first_record, OCRHandler().claims(first_record, first_payload))
        _register_active_task(context, second_record, OCRHandler().claims(second_record, second_payload))

        state = context.services.document.get_ocr(project_id, document_id)

        assert state.active_task_id in {first_record.task_id, second_record.task_id}
        assert set(state.active_task_ids) == {first_record.task_id, second_record.task_id}
        assert state.progress is not None
        assert state.progress.current == 3
        assert state.progress.total == 7
    finally:
        context.close()


def test_document_service_get_ocr_marks_run_current_per_page_when_other_page_is_active(
    tmp_path: Path,
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Per Page Actions", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("scanned_book")
            idle_source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            active_source_id = repo.insert_document_source(
                document_id,
                1,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
            )
            db.commit()
        finally:
            db.close()

        active_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="ocr",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [active_source_id]}),
        )
        active_payload = OCRHandler().decode_payload(active_record)
        _register_active_task(context, active_record, OCRHandler().claims(active_record, active_payload))

        state = context.services.document.get_ocr(project_id, document_id)

        page_by_source_id = {page.source_id: page for page in state.pages}
        assert page_by_source_id[idle_source_id].run_action.enabled
        assert page_by_source_id[idle_source_id].run_action.blocker is None
        assert not page_by_source_id[active_source_id].run_action.enabled
        assert page_by_source_id[active_source_id].run_action.blocker is not None
    finally:
        context.close()


def test_document_service_run_ocr_is_blocked_after_chunking_starts(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Run Blocked", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("pdf")
            source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"text": "before edit"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    ChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="before edit",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        with pytest.raises(ApplicationError) as exc_info:
            context.services.document.run_ocr(
                RunOCRRequest(project_id=project_id, document_id=document_id, source_id=source_id)
            )

        assert exc_info.value.payload.code == ApplicationErrorCode.BLOCKED
        assert (
            exc_info.value.payload.message == "OCR is locked after terms or translation have started for this document."
        )
    finally:
        context.close()


def test_document_service_save_ocr_preserves_structured_payload_shape(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Structured", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("pdf")
            source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps(
                    [
                        {
                            "page_type": "content",
                            "content": [
                                {"type": "paragraph", "text": "line one"},
                                {"type": "paragraph", "text": "line two"},
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                is_ocr_completed=True,
            )
            db.commit()
        finally:
            db.close()

        state = context.services.document.save_ocr(
            SaveOCRPageRequest(
                project_id=project_id,
                document_id=document_id,
                source_id=source_id,
                extracted_text="edited one\nedited two",
                elements=[
                    OCRTextElement(element_id=0, text="edited one"),
                    OCRTextElement(element_id=1, text="edited two"),
                ],
            )
        )

        assert state.pages[0].elements[0].text == "edited one"
        assert state.pages[0].elements[1].text == "edited two"

        db, repo = _open_repo(context, project_id)
        try:
            saved = repo.get_source_ocr_json(source_id)
        finally:
            db.close()

        assert saved is not None
        payload = json.loads(saved)
        assert isinstance(payload, list)
        assert payload[0]["content"][0]["text"] == "edited one"
        assert payload[0]["content"][1]["text"] == "edited two"
    finally:
        context.close()


def test_document_service_save_ocr_is_blocked_after_chunking_starts(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR After Chunking", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("pdf")
            source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"text": "before edit"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    ChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="before edit",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        with pytest.raises(ApplicationError) as exc_info:
            context.services.document.save_ocr(
                SaveOCRPageRequest(
                    project_id=project_id,
                    document_id=document_id,
                    source_id=source_id,
                    extracted_text="after edit",
                )
            )

        assert exc_info.value.payload.code == ApplicationErrorCode.BLOCKED
        assert (
            exc_info.value.payload.message == "OCR is locked after terms or translation have started for this document."
        )

        db, repo = _open_repo(context, project_id)
        try:
            saved = repo.get_source_ocr_json(source_id)
            chunks = db.list_chunks(document_id=document_id)
            terms = db.list_terms()
        finally:
            db.close()
        assert saved is not None
        assert json.loads(saved)["text"] == "before edit"
        assert len(chunks) == 1
        assert terms == []
    finally:
        context.close()


def test_document_service_save_ocr_does_not_invalidate_later_documents_when_blocked(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    seen_events: list[object] = []
    subscription = context.events.subscribe(lambda event: seen_events.append(event))
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="OCR Stack Invalidation", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("pdf")
            later_document_id = repo.insert_document("pdf")
            source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"text": "before edit"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    ChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="before edit",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                    ),
                    ChunkRecord(
                        chunk_id=2,
                        hash="chunk-2",
                        text="later doc",
                        document_id=later_document_id,
                        is_extracted=True,
                        is_summarized=True,
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        with pytest.raises(ApplicationError) as exc_info:
            context.services.document.save_ocr(
                SaveOCRPageRequest(
                    project_id=project_id,
                    document_id=document_id,
                    source_id=source_id,
                    extracted_text="after edit",
                )
            )

        assert exc_info.value.payload.code == ApplicationErrorCode.BLOCKED
        document_events = [event for event in seen_events if isinstance(event, DocumentInvalidatedEvent)]
        assert document_events == []
    finally:
        subscription.close()
        context.close()


def test_document_service_translation_run_blocker_prefers_translation_context(tmp_path: Path, monkeypatch) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="Translation Blocker", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("text")
            db.upsert_chunks(
                [
                    ChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="hello",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        original_preflight = context.runtime.task_engine.preflight

        def _preflight(task_type, book_id, params, action):  # noqa: ANN001
            if task_type in {"translation_text", "batch_translation"}:
                from context_aware_translation.workflow.tasks.models import Decision

                return Decision(
                    allowed=False,
                    code="config_snapshot_unavailable",
                    reason="Translation needs setup before it can run.",
                )
            return original_preflight(task_type, book_id, params, action)

        monkeypatch.setattr(context.runtime.task_engine, "preflight", _preflight, raising=True)

        state = context.services.document.get_translation(project_id, document_id)

        assert not state.run_action.enabled
        assert state.run_action.blocker is not None
        assert state.run_action.blocker.target is not None
        assert state.run_action.blocker.target.kind == "app_setup"
    finally:
        context.close()


def test_document_service_get_images_prefers_translation_running_message_on_claim_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Images While Translating", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("manga")
            repo.insert_document_source(
                document_id,
                0,
                "image",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"text": "jp line"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    TranslationChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="jp line",
                        translation="en line",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                        is_translated=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        original_preflight = context.runtime.task_engine.preflight

        def _preflight(task_type, book_id, params, action):  # noqa: ANN001
            if task_type == "image_reembedding":
                from context_aware_translation.workflow.tasks.models import Decision

                return Decision(allowed=False, code="blocked_claim_conflict", reason="Task is already running")
            return original_preflight(task_type, book_id, params, action)

        monkeypatch.setattr(context.runtime.task_engine, "preflight", _preflight, raising=True)
        monkeypatch.setattr(
            context.services.document,
            "_active_translation_task",
            lambda _project_id, _document_id: object(),
            raising=True,
        )

        state = context.services.document.get_images(project_id, document_id)

        assert not state.toolbar.can_run_pending
        assert state.toolbar.run_pending_blocker is not None
        assert state.toolbar.run_pending_blocker.message == "Translation is already running for this document."
        assert state.toolbar.force_all_blocker is not None
        assert state.toolbar.force_all_blocker.message == "Translation is already running for this document."
        assert state.assets
        assert state.assets[0].run_blocker is not None
        assert state.assets[0].run_blocker.message == "Translation is already running for this document."
    finally:
        context.close()


def test_document_service_get_images_epub_skips_full_text_reinjection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Images Fast Path", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            repo.insert_document_source(
                document_id,
                0,
                "text",
                relative_path="chapter.xhtml",
                text_content="<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>",
                mime_type="application/xhtml+xml",
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                1,
                "image",
                relative_path="image.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"embedded_text": "img jp"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    TranslationChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="Before ⟪RUBY:0⟫漢字⟪/RUBY:0⟫ after\nimg jp",
                        translation="Before ⟪RUBY:0⟫漢字⟪/RUBY:0⟫ after\nimg en",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                        is_translated=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        async def _unexpected_set_text(self, lines, cancel_check=None, progress_callback=None):  # noqa: ANN001, ARG001
            raise AssertionError("EPUB image loading should not rebuild full chapter translations.")

        monkeypatch.setattr(
            "context_aware_translation.documents.epub.EPUBDocument.set_text",
            _unexpected_set_text,
        )

        state = context.services.document.get_images(project_id, document_id)

        assert len(state.assets) == 1
        assert state.assets[0].translated_text == "img en"
    finally:
        context.close()


def test_document_service_get_images_reuses_shared_preflight_for_asset_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Images Shared Preflight", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            db.commit()
        finally:
            db.close()

        monkeypatch.setattr(
            context.services.document,
            "_build_image_assets",
            lambda *_args, **_kwargs: [
                ImageAssetState(
                    asset_id="1",
                    label="Image 1",
                    status=SurfaceStatus.READY,
                    source_id=101,
                    translated_text="one",
                    original_image_bytes=b"one",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
                ImageAssetState(
                    asset_id="2",
                    label="Image 2",
                    status=SurfaceStatus.READY,
                    source_id=102,
                    translated_text="two",
                    original_image_bytes=b"two",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
                ImageAssetState(
                    asset_id="3",
                    label="Image 3",
                    status=SurfaceStatus.DONE,
                    source_id=103,
                    translated_text="three",
                    original_image_bytes=b"three",
                    reembedded_image_bytes=b"done",
                    can_run=False,
                    run_blocker=None,
                ),
            ],
            raising=True,
        )

        original_preflight = context.runtime.task_engine.preflight
        calls: list[dict[str, object]] = []

        def _preflight(task_type, book_id, params, action):  # noqa: ANN001
            if task_type == "image_reembedding":
                from context_aware_translation.workflow.tasks.models import Decision

                calls.append(dict(params))
                return Decision(allowed=True)
            return original_preflight(task_type, book_id, params, action)

        monkeypatch.setattr(context.runtime.task_engine, "preflight", _preflight, raising=True)

        state = context.services.document.get_images(project_id, document_id)

        assert len(calls) == 3
        assert calls == [
            {"document_ids": [document_id], "force": True},
            {"document_ids": [document_id], "force": False},
            {"document_ids": [document_id], "force": True},
        ]
        assert all(asset.can_run for asset in state.assets)
        assert all(asset.run_blocker is None for asset in state.assets)
        assert state.toolbar.can_run_pending
        assert state.toolbar.can_force_all
    finally:
        context.close()


def test_document_service_get_images_allows_other_source_while_source_task_is_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Images Parallel Sources", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            idle_source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                relative_path="idle.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                is_ocr_completed=True,
            )
            running_source_id = repo.insert_document_source(
                document_id,
                1,
                "image",
                relative_path="running.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    TranslationChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="img jp",
                        translation="img zh",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                        is_translated=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        active_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="image_reembedding",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [running_source_id], "force": True}),
        )
        active_payload = ImageReembeddingHandler().decode_payload(active_record)
        _register_active_task(context, active_record, ImageReembeddingHandler().claims(active_record, active_payload))

        monkeypatch.setattr(
            context.services.document,
            "_build_image_assets",
            lambda *_args, **_kwargs: [
                ImageAssetState(
                    asset_id=str(idle_source_id),
                    label="Image 1",
                    status=SurfaceStatus.READY,
                    source_id=idle_source_id,
                    translated_text="idle",
                    original_image_bytes=b"idle",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
                ImageAssetState(
                    asset_id=str(running_source_id),
                    label="Image 2",
                    status=SurfaceStatus.RUNNING,
                    source_id=running_source_id,
                    translated_text="running",
                    original_image_bytes=b"running",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
            ],
            raising=True,
        )

        state = context.services.document.get_images(project_id, document_id)

        asset_by_source_id = {asset.source_id: asset for asset in state.assets}
        assert asset_by_source_id[idle_source_id].can_run
        assert asset_by_source_id[idle_source_id].run_blocker is None
        assert asset_by_source_id[running_source_id].status is SurfaceStatus.RUNNING
        assert not asset_by_source_id[running_source_id].can_run
        assert asset_by_source_id[running_source_id].run_blocker is not None
        assert not state.toolbar.can_run_pending
        assert state.toolbar.run_pending_blocker is not None
        assert state.toolbar.can_cancel
    finally:
        context.close()


def test_document_service_get_images_aggregates_multiple_active_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Images Parallel Progress", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            first_source_id = repo.insert_document_source(
                document_id,
                0,
                "image",
                relative_path="first.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                is_ocr_completed=True,
            )
            second_source_id = repo.insert_document_source(
                document_id,
                1,
                "image",
                relative_path="second.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    TranslationChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="img jp",
                        translation="img zh",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                        is_translated=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        first_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="image_reembedding",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [first_source_id], "force": True}),
        )
        second_record = context.runtime.task_store.create(
            book_id=project_id,
            task_type="image_reembedding",
            status="running",
            document_ids_json=json.dumps([document_id]),
            payload_json=json.dumps({"document_ids": [document_id], "source_ids": [second_source_id], "force": True}),
        )
        first_record = context.runtime.task_store.update(first_record.task_id, completed_items=1, total_items=2)
        second_record = context.runtime.task_store.update(second_record.task_id, completed_items=3, total_items=5)
        first_payload = ImageReembeddingHandler().decode_payload(first_record)
        second_payload = ImageReembeddingHandler().decode_payload(second_record)
        _register_active_task(context, first_record, ImageReembeddingHandler().claims(first_record, first_payload))
        _register_active_task(context, second_record, ImageReembeddingHandler().claims(second_record, second_payload))

        monkeypatch.setattr(
            context.services.document,
            "_build_image_assets",
            lambda *_args, **_kwargs: [
                ImageAssetState(
                    asset_id=str(first_source_id),
                    label="Image 1",
                    status=SurfaceStatus.RUNNING,
                    source_id=first_source_id,
                    translated_text="first",
                    original_image_bytes=b"first",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
                ImageAssetState(
                    asset_id=str(second_source_id),
                    label="Image 2",
                    status=SurfaceStatus.RUNNING,
                    source_id=second_source_id,
                    translated_text="second",
                    original_image_bytes=b"second",
                    reembedded_image_bytes=None,
                    can_run=False,
                    run_blocker=None,
                ),
            ],
            raising=True,
        )

        state = context.services.document.get_images(project_id, document_id)

        assert state.active_task_id in {first_record.task_id, second_record.task_id}
        assert set(state.active_task_ids) == {first_record.task_id, second_record.task_id}
        assert state.progress is not None
        assert state.progress.current == 4
        assert state.progress.total == 7
    finally:
        context.close()


def test_document_service_get_images_epub_avoids_full_source_blob_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Images Light Source Fetch", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            repo.insert_document_source(
                document_id,
                0,
                "text",
                relative_path="chapter.xhtml",
                text_content="<html><body><p>chapter</p></body></html>",
                mime_type="application/xhtml+xml",
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                1,
                "image",
                relative_path="image.png",
                binary_content=_tiny_png_bytes(),
                mime_type="image/png",
                ocr_json=json.dumps({"embedded_text": "img jp"}, ensure_ascii=False),
                is_ocr_completed=True,
            )
            db.upsert_chunks(
                [
                    TranslationChunkRecord(
                        chunk_id=1,
                        hash="chunk-1",
                        text="chapter\nimg jp",
                        translation="chapter\nimg en",
                        document_id=document_id,
                        is_extracted=True,
                        is_summarized=True,
                        is_translated=True,
                    )
                ]
            )
            db.commit()
        finally:
            db.close()

        def _unexpected_get_document_sources(self, document_id_arg):  # noqa: ANN001, ARG001
            raise AssertionError("EPUB image loading should avoid fetching full source rows with binary blobs.")

        monkeypatch.setattr(
            DocumentRepository,
            "get_document_sources",
            _unexpected_get_document_sources,
        )

        state = context.services.document.get_images(project_id, document_id)

        assert len(state.assets) == 1
        assert state.assets[0].translated_text == "img en"
    finally:
        context.close()


def test_document_service_get_images_manga_without_ocr_config_is_setup_blocked(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Images Without OCR Config", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)
        config = context.runtime.get_effective_config_payload(project_id)
        config.pop("ocr_config", None)
        context.runtime.book_manager.set_book_custom_config(project_id, config)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("manga")
            db.commit()
        finally:
            db.close()

        state = context.services.document.get_images(project_id, document_id)

        assert not state.toolbar.can_run_pending
        assert not state.toolbar.can_force_all
        assert state.toolbar.run_pending_blocker is not None
        assert state.toolbar.force_all_blocker is not None
        assert state.toolbar.run_pending_blocker.target is not None
        assert state.toolbar.force_all_blocker.target is not None
        assert state.toolbar.run_pending_blocker.target.kind == "project_setup"
        assert state.toolbar.force_all_blocker.target.kind == "project_setup"
    finally:
        context.close()


def test_document_service_get_images_hides_unsupported_document_type_blocker(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="Plain Text Images", target_language="English")
        )
        project_id = project.project.project_id
        _configure_project_for_ocr(context, project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("text")
            db.commit()
        finally:
            db.close()

        state = context.services.document.get_images(project_id, document_id)

        assert state.assets == []
        assert not state.toolbar.can_run_pending
        assert not state.toolbar.can_force_all
        assert state.toolbar.run_pending_blocker is None
        assert state.toolbar.force_all_blocker is None
    finally:
        context.close()


def test_epub_asset_migration_hides_non_image_sources_from_ocr_and_workboard(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB OCR Migration", target_language="English")
        )
        project_id = project.project.project_id
        book_db_path = context.runtime.book_manager.get_book_db_path(project_id)

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            repo.insert_document_source(
                document_id,
                0,
                "text",
                relative_path="__epub_metadata__.json",
                text_content=json.dumps({}, ensure_ascii=False),
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                1,
                "image",
                relative_path="__epub_original__.epub",
                binary_content=b"epub-bytes",
                mime_type="application/epub+zip",
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                2,
                "image",
                relative_path="OEBPS/nav.xhtml",
                binary_content=b"<html></html>",
                mime_type="application/xhtml+xml",
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                3,
                "image",
                relative_path="OEBPS/toc.ncx",
                binary_content=b"<ncx></ncx>",
                mime_type="application/x-dtbncx+xml",
                is_text_added=True,
                is_ocr_completed=True,
            )
            db.commit()
        finally:
            db.close()

        with sqlite3.connect(book_db_path) as raw:
            raw.execute("UPDATE meta SET schema_version = 2")
            raw.commit()

        ocr_state = context.services.document.get_ocr(project_id, document_id)
        assert ocr_state.pages == []

        workboard = context.services.work.get_workboard(project_id)
        assert len(workboard.rows) == 1
        assert workboard.rows[0].document.label == "nav.xhtml"
        assert workboard.rows[0].ocr_status == "N/A"

        db, repo = _open_repo(context, project_id)
        try:
            sources = repo.get_document_sources(document_id)
        finally:
            db.close()

        source_types = {source["relative_path"]: source["source_type"] for source in sources}
        assert source_types["__epub_original__.epub"] == "asset"
        assert source_types["OEBPS/nav.xhtml"] == "asset"
        assert source_types["OEBPS/toc.ncx"] == "asset"
    finally:
        context.close()


def test_workboard_uses_epub_archive_filename_for_label(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        project = context.services.projects.create_project(
            CreateProjectRequest(name="EPUB Label", target_language="English")
        )
        project_id = project.project.project_id

        db, repo = _open_repo(context, project_id)
        try:
            document_id = repo.insert_document("epub")
            repo.insert_document_source(
                document_id,
                0,
                "text",
                relative_path="__epub_metadata__.json",
                text_content=json.dumps({}, ensure_ascii=False),
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                1,
                "asset",
                relative_path="my-book.epub",
                binary_content=b"epub-bytes",
                mime_type="application/epub+zip",
                is_text_added=True,
                is_ocr_completed=True,
            )
            repo.insert_document_source(
                document_id,
                2,
                "text",
                relative_path="OEBPS/chapter-1.xhtml",
                text_content="<html></html>",
                mime_type="application/xhtml+xml",
                is_text_added=True,
                is_ocr_completed=True,
            )
            db.commit()
        finally:
            db.close()

        workboard = context.services.work.get_workboard(project_id)
        assert len(workboard.rows) == 1
        assert workboard.rows[0].document.label == "my-book.epub"
    finally:
        context.close()
