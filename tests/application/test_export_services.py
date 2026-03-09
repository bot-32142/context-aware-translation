from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PySide6.QtCore import QCoreApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.document import RunDocumentExportRequest
from context_aware_translation.application.contracts.projects import CreateProjectRequest
from context_aware_translation.application.contracts.work import PrepareExportRequest, RunExportRequest
from context_aware_translation.storage.book_db import TranslationChunkRecord


def _ensure_qt_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def _insert_text_document(
    context,
    project_id: str,
    *,
    chunk_id: int,
    translated: bool,
    label: str,
) -> int:
    with context.runtime.open_book_db(project_id) as dbx:
        document_id = dbx.document_repo.insert_document("text")
        dbx.document_repo.insert_document_source(
            document_id,
            0,
            "text",
            relative_path=label,
            text_content="hello world",
            is_ocr_completed=True,
        )
        dbx.db.upsert_chunks(
            [
                TranslationChunkRecord(
                    chunk_id=chunk_id,
                    hash=f"hash-{chunk_id}",
                    text="hello world",
                    normalized_text="hello world",
                    document_id=document_id,
                    is_extracted=True,
                    is_occurrence_mapped=True,
                    is_translated=translated,
                    translation="hello world translated" if translated else None,
                )
            ]
        )
    return document_id


def test_prepare_export_exposes_fallback_and_preserve_structure(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Export Test", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _insert_text_document(context, project_id, chunk_id=1, translated=False, label="chapter-01.txt")

        state = context.services.work.prepare_export(
            PrepareExportRequest(project_id=project_id, document_ids=[document_id])
        )

        assert state.document_labels == ["chapter-01.txt"]
        assert state.supports_preserve_structure is True
        assert state.incomplete_translation_message is not None
        assert Path(state.default_output_path).suffix == f".{state.available_formats[0].format_id}"
    finally:
        context.close()


def test_work_run_export_calls_backend_ops_with_options(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Export Run", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _insert_text_document(context, project_id, chunk_id=1, translated=False, label="chapter-01.txt")
        state = context.services.work.prepare_export(
            PrepareExportRequest(project_id=project_id, document_ids=[document_id])
        )
        session = MagicMock()
        session.__enter__.return_value = MagicMock(name="workflow")
        session.__exit__.return_value = False

        with (
            patch(
                "context_aware_translation.application.services._export_support.WorkflowSession.from_book",
                return_value=session,
            ),
            patch(
                "context_aware_translation.application.services._export_support.export_ops.export_preserve_structure",
                new_callable=AsyncMock,
            ) as export_mock,
        ):
            result = context.services.work.run_export(
                RunExportRequest(
                    project_id=project_id,
                    document_ids=[document_id],
                    format_id=state.available_formats[0].format_id,
                    output_path=str(tmp_path / "out"),
                    options={"preserve_structure": True, "allow_original_fallback": True},
                )
            )

        export_mock.assert_awaited_once()
        kwargs = export_mock.await_args.kwargs
        assert kwargs["document_ids"] == [document_id]
        assert kwargs["allow_original_fallback"] is True
        assert kwargs["output_folder"] == tmp_path / "out"
        assert result.document_id == document_id
        assert result.exported_count == 1
    finally:
        context.close()


def test_document_export_state_and_execution_use_document_service(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Document Export", target_language="English")
        )
        project_id = created.project.project_id
        document_id = _insert_text_document(context, project_id, chunk_id=1, translated=True, label="page-04.txt")

        state = context.services.document.get_export(project_id, document_id)
        assert state.can_export is True
        assert state.supports_preserve_structure is True
        assert state.incomplete_translation_message is None

        session = MagicMock()
        session.__enter__.return_value = MagicMock(name="workflow")
        session.__exit__.return_value = False
        with (
            patch(
                "context_aware_translation.application.services._export_support.WorkflowSession.from_book",
                return_value=session,
            ),
            patch(
                "context_aware_translation.application.services._export_support.export_ops.export",
                new_callable=AsyncMock,
            ) as export_mock,
        ):
            result = context.services.document.export_document(
                RunDocumentExportRequest(
                    project_id=project_id,
                    document_id=document_id,
                    format_id=state.available_formats[0].format_id,
                    output_path=str(tmp_path / "page-04.txt"),
                )
            )

        export_mock.assert_awaited_once()
        kwargs = export_mock.await_args.kwargs
        assert kwargs["document_ids"] == [document_id]
        assert kwargs["export_format"] == state.available_formats[0].format_id
        assert kwargs["file_path"] == tmp_path / "page-04.txt"
        assert result.document_id == document_id
        assert result.output_path.endswith("page-04.txt")
    finally:
        context.close()
