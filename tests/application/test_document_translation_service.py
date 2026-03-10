from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.common import AcceptedCommand, ProjectRef, SurfaceStatus
from context_aware_translation.application.contracts.document import (
    RetranslateRequest,
    RunDocumentTranslationRequest,
    SaveTranslationRequest,
    TranslationUnitKind,
)
from context_aware_translation.application.contracts.projects import CreateProjectRequest
from context_aware_translation.application.contracts.terms import TermsScope, TermsScopeKind, TermsTableState
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode
from context_aware_translation.storage.book_db import TranslationChunkRecord
from context_aware_translation.workflow.tasks.models import Decision


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _empty_terms(project_id: str) -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(kind=TermsScopeKind.DOCUMENT, project=ProjectRef(project_id=project_id, name="Project")),
    )


def _insert_chunk(
    context,
    project_id: str,
    *,
    chunk_id: int,
    document_id: int,
    text: str,
    translation: str | None = None,
    is_translated: bool = False,
) -> None:
    with context.runtime.open_book_db(project_id) as dbx:
        dbx.db.upsert_chunks(
            [
                TranslationChunkRecord(
                    chunk_id=chunk_id,
                    hash=f"hash-{chunk_id}",
                    text=text,
                    document_id=document_id,
                    created_at=time.time(),
                    is_extracted=True,
                    is_summarized=True,
                    is_occurrence_mapped=True,
                    is_translated=is_translated,
                    translation=translation,
                )
            ]
        )


def _create_text_document(context, project_id: str) -> int:
    with context.runtime.open_book_db(project_id) as dbx:
        document_id = dbx.document_repo.insert_document("text")
        dbx.document_repo.insert_document_source(
            document_id,
            0,
            "text",
            text_content="source",
            is_text_added=True,
        )
    _insert_chunk(context, project_id, chunk_id=1, document_id=document_id, text="Line 1\nLine 2")
    _insert_chunk(
        context,
        project_id,
        chunk_id=2,
        document_id=document_id,
        text="Single line",
        translation="Translated line",
        is_translated=True,
    )
    return document_id


def _create_manga_document(context, project_id: str) -> tuple[int, int, int, int]:
    with context.runtime.open_book_db(project_id) as dbx:
        document_id = dbx.document_repo.insert_document("manga")
        source_1 = dbx.document_repo.insert_document_source(
            document_id,
            0,
            "image",
            ocr_json=json.dumps({"regions": [{"text": "一行目\n二行目"}]}),
            is_ocr_completed=True,
        )
        source_2 = dbx.document_repo.insert_document_source(
            document_id,
            1,
            "image",
            ocr_json=json.dumps({"regions": [{"text": ""}]}),
            is_ocr_completed=True,
        )
        source_3 = dbx.document_repo.insert_document_source(
            document_id,
            2,
            "image",
            ocr_json=json.dumps({"regions": [{"text": "最後のページ"}]}),
            is_ocr_completed=True,
        )
    _insert_chunk(
        context,
        project_id,
        chunk_id=10,
        document_id=document_id,
        text="一行目\n二行目",
        translation="First page",
        is_translated=True,
    )
    _insert_chunk(
        context,
        project_id,
        chunk_id=11,
        document_id=document_id,
        text="最後のページ",
    )
    return document_id, source_1, source_2, source_3


def test_get_translation_builds_text_units_and_progress(tmp_path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Text Doc", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _create_text_document(context, project_id)

        service = context.services.document
        service.get_terms = MagicMock(return_value=_empty_terms(project_id))  # type: ignore[method-assign]
        context.runtime.task_engine.has_active_claims = MagicMock(return_value=False)
        context.runtime.task_engine.preflight = MagicMock(return_value=Decision(allowed=True))

        state = service.get_translation(project_id, document_id)

        assert [unit.unit_id for unit in state.units] == ["1", "2"]
        assert state.units[0].unit_kind is TranslationUnitKind.CHUNK
        assert state.units[0].actions.can_save is True
        assert state.units[0].actions.can_retranslate is True
        assert state.progress is not None
        assert state.progress.current == 1
        assert state.progress.total == 2
        assert state.current_unit_id == "1"
    finally:
        context.close()


def test_save_translation_rejects_line_count_mismatch_for_chunk(tmp_path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Text Doc", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _create_text_document(context, project_id)

        service = context.services.document
        context.runtime.task_engine.has_active_claims = MagicMock(return_value=False)

        try:
            service.save_translation(
                SaveTranslationRequest(
                    project_id=project_id,
                    document_id=document_id,
                    unit_id="1",
                    translated_text="Only one line",
                )
            )
        except ApplicationError as exc:
            assert exc.payload.code is ApplicationErrorCode.VALIDATION
            assert "expected 2 lines" in exc.payload.message
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected validation error")
    finally:
        context.close()


def test_get_translation_builds_manga_page_units_and_art_only_blockers(tmp_path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Doc", target_language="English")
        )
        project_id = created.project.project_id
        document_id, source_1, source_2, source_3 = _create_manga_document(context, project_id)

        service = context.services.document
        service.get_terms = MagicMock(return_value=_empty_terms(project_id))  # type: ignore[method-assign]
        context.runtime.task_engine.has_active_claims = MagicMock(return_value=False)
        context.runtime.task_engine.preflight = MagicMock(return_value=Decision(allowed=True))

        state = service.get_translation(project_id, document_id)

        assert [unit.unit_id for unit in state.units] == [str(source_1), str(source_2), str(source_3)]
        assert state.units[0].unit_kind is TranslationUnitKind.PAGE
        assert state.units[0].source_id == source_1
        assert state.units[0].translated_text == "First page"
        assert state.units[1].status is SurfaceStatus.BLOCKED
        assert state.units[1].blocker is not None
        assert "No OCR text detected" in state.units[1].blocker.message
        assert state.units[2].translated_text is None
        assert state.current_unit_id == str(source_1)
    finally:
        context.close()


def test_retranslate_manga_page_submits_scoped_translation_task(tmp_path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Doc", target_language="English")
        )
        project_id = created.project.project_id
        document_id, _source_1, _source_2, source_3 = _create_manga_document(context, project_id)

        service = context.services.document
        context.runtime.task_engine.preflight = MagicMock(return_value=Decision(allowed=True))
        context.runtime.task_engine.submit_and_start = MagicMock(
            return_value=SimpleNamespace(task_id="task-1", status="queued")
        )

        command = service.retranslate(
            RetranslateRequest(
                project_id=project_id,
                document_id=document_id,
                unit_id=str(source_3),
            )
        )

        assert command.command_name == "translation_manga"
        context.runtime.task_engine.submit_and_start.assert_called_once_with(
            "translation_manga",
            project_id,
            document_ids=[document_id],
            source_ids=[source_3],
            force=True,
        )
    finally:
        context.close()


def test_run_translation_submits_document_translation_task(tmp_path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Text Doc", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _create_text_document(context, project_id)

        service = context.services.document
        with patch.object(
            type(context.runtime),
            "submit_task",
            return_value=AcceptedCommand(command_name="translation_text", command_id="task-1"),
        ) as mock_submit:
            command = service.run_translation(
                RunDocumentTranslationRequest(project_id=project_id, document_id=document_id)
            )

        assert command.command_name == "translation_text"
        mock_submit.assert_called_once_with(
            "translation_text",
            project_id,
            document_ids=[document_id],
        )
    finally:
        context.close()
