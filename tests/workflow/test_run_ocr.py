from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_aware_translation.documents.base import Document
from context_aware_translation.workflow.ops import ocr_ops
from context_aware_translation.workflow.runtime import WorkflowContext


@pytest.mark.asyncio
async def test_run_ocr_with_empty_source_ids_processes_none():
    config = MagicMock()
    config.ocr_config = object()

    llm_client = MagicMock()
    context_tree = MagicMock()
    manager = MagicMock()
    db = MagicMock()
    document_repo = MagicMock()
    document_repo.get_document_sources_needing_ocr.return_value = [
        {"source_id": 1},
        {"source_id": 2},
    ]

    document = MagicMock()
    document.document_id = 10
    document.process_ocr = AsyncMock(return_value=0)

    context = WorkflowContext(
        config=config,
        llm_client=llm_client,
        context_tree=context_tree,
        manager=manager,
        db=db,
        document_repo=document_repo,
    )

    progress_callback = MagicMock()
    with patch("context_aware_translation.documents.base.Document.load_all", return_value=[document]):
        processed = await ocr_ops.run_ocr(
            context,
            document_loader=Document.load_all,
            progress_callback=progress_callback,
            source_ids=[],
        )

    assert processed == 0
    progress_callback.assert_not_called()
    document.process_ocr.assert_awaited_once_with(llm_client, [])
