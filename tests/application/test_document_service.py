from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.document import OCRTextElement, SaveOCRPageRequest
from context_aware_translation.application.contracts.projects import CreateProjectRequest
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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


def test_document_service_get_ocr_allows_current_page_rerun_after_completion(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
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


def test_document_service_save_ocr_preserves_structured_payload_shape(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
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
