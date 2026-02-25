"""Tests for TaskRowVM mapper — pure functions, no PySide6 dependency."""

from __future__ import annotations

import time

import pytest

from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.ui.tasks import (
    TaskRowVM,
    map_task_to_row_vm,
    map_tasks_to_row_vms,
)


def _make_record(**overrides) -> TaskRecord:
    defaults = dict(
        task_id="abcd1234-5678-9abc-def0-1234567890ab",
        book_id="book-001",
        task_type="batch_translation",
        status="running",
        phase="translating",
        document_ids_json=None,
        payload_json=None,
        cancel_requested=False,
        total_items=10,
        completed_items=3,
        failed_items=0,
        last_error=None,
        created_at=time.time(),
        updated_at=time.time(),
    )
    defaults.update(overrides)
    return TaskRecord(**defaults)


class TestTitleMapping:
    def test_batch_translation_title(self):
        vm = map_task_to_row_vm(_make_record(task_type="batch_translation"))
        assert vm.title == "Batch Translation #abcd1234"

    def test_glossary_extraction_title(self):
        vm = map_task_to_row_vm(_make_record(task_type="glossary_extraction"))
        assert vm.title == "Glossary Extraction #abcd1234"

    def test_unknown_type_raises(self):
        with pytest.raises(RuntimeError, match="Unknown task type"):
            map_task_to_row_vm(_make_record(task_type="unknown_type"))


class TestScopeLabel:
    def test_all_documents_when_null(self):
        vm = map_task_to_row_vm(_make_record(document_ids_json=None))
        assert vm.scope_label == "All documents"

    def test_all_documents_when_empty_list(self):
        vm = map_task_to_row_vm(_make_record(document_ids_json="[]"))
        assert vm.scope_label == "All documents"

    def test_single_document(self):
        vm = map_task_to_row_vm(_make_record(document_ids_json="[1]"))
        assert vm.scope_label == "1 document"

    def test_multiple_documents(self):
        vm = map_task_to_row_vm(_make_record(document_ids_json="[1,2,3]"))
        assert vm.scope_label == "3 documents"

    def test_invalid_json_falls_back(self):
        vm = map_task_to_row_vm(_make_record(document_ids_json="{bad"))
        assert vm.scope_label == "All documents"


class TestProgressNormalization:
    def test_negative_values_clamped_to_zero(self):
        vm = map_task_to_row_vm(
            _make_record(completed_items=-1, total_items=-5, failed_items=-2)
        )
        assert vm.completed_items == 0
        assert vm.total_items == 0
        assert vm.failed_items == 0

    def test_positive_values_preserved(self):
        vm = map_task_to_row_vm(
            _make_record(completed_items=7, total_items=10, failed_items=1)
        )
        assert vm.completed_items == 7
        assert vm.total_items == 10
        assert vm.failed_items == 1

    def test_none_and_invalid_values_coerced_to_zero(self):
        vm = map_task_to_row_vm(
            _make_record(
                completed_items=None,  # type: ignore[arg-type]
                total_items="bad",  # type: ignore[arg-type]
                failed_items="3",  # type: ignore[arg-type]
            )
        )
        assert vm.completed_items == 0
        assert vm.total_items == 0
        assert vm.failed_items == 3


class TestNullFields:
    def test_null_phase(self):
        vm = map_task_to_row_vm(_make_record(phase=None))
        assert vm.phase is None

    def test_null_last_error(self):
        vm = map_task_to_row_vm(_make_record(last_error=None))
        assert vm.last_error is None

    def test_phase_and_error_present(self):
        vm = map_task_to_row_vm(
            _make_record(phase="extracting", last_error="timeout")
        )
        assert vm.phase == "extracting"
        assert vm.last_error == "timeout"


class TestBatchMapping:
    def test_empty_list(self):
        assert map_tasks_to_row_vms([]) == []

    def test_preserves_order(self):
        r1 = _make_record(task_id="aaaa1111-0000-0000-0000-000000000000")
        r2 = _make_record(task_id="bbbb2222-0000-0000-0000-000000000000")
        vms = map_tasks_to_row_vms([r1, r2])
        assert len(vms) == 2
        assert vms[0].task_id == "aaaa1111-0000-0000-0000-000000000000"
        assert vms[1].task_id == "bbbb2222-0000-0000-0000-000000000000"

    def test_returns_task_row_vm_instances(self):
        vms = map_tasks_to_row_vms([_make_record()])
        assert isinstance(vms[0], TaskRowVM)
