from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from context_aware_translation.application.contracts.app_setup import (
    CapabilityCard,
    ConnectionStatus,
    ConnectionSummary,
    DefaultRoute,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    CapabilityAvailability,
    CapabilityCode,
    DocumentRef,
    DocumentSection,
    DocumentTypeCode,
    NavigationTarget,
    NavigationTargetKind,
    ProgressInfo,
    ProjectRef,
    ProviderKind,
    QueueActionKind,
    QueueStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.projects import ProjectSummary
from context_aware_translation.application.contracts.queue import QueueItem
from context_aware_translation.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    ApplicationErrorPayload,
    BlockedOperationError,
)
from context_aware_translation.application.events import (
    ApplicationEventPublisher,
    DocumentInvalidatedEvent,
    ProjectsInvalidatedEvent,
    QueueChangedEvent,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
    WorkboardInvalidatedEvent,
)
from context_aware_translation.config import Config
from context_aware_translation.storage.book import Book
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.config_profile import ConfigProfile
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.storage.endpoint_profile import EndpointProfile
from context_aware_translation.storage.task_store import TaskRecord, TaskStore
from context_aware_translation.storage.term_repository import TermRepository
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from context_aware_translation.ui.tasks.qt_task_engine import TaskEngine
    from context_aware_translation.workflow.tasks.models import Decision
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_DEFAULT_PROFILE_NAME = "app-default-profile"
_UI_PRESET_KEY = "_ui_preset"


@dataclass(frozen=True)
class BookDBContext:
    db: SQLiteBookDB
    document_repo: DocumentRepository
    term_repo: TermRepository


@dataclass(frozen=True)
class ApplicationRuntime:
    book_manager: BookManager
    task_store: TaskStore
    task_engine: TaskEngine
    worker_deps: WorkerDeps
    events: ApplicationEventPublisher

    @contextmanager
    def open_book_db(self, project_id: str) -> Iterator[BookDBContext]:
        db = SQLiteBookDB(self.book_manager.get_book_db_path(project_id))
        try:
            yield BookDBContext(db=db, document_repo=DocumentRepository(db), term_repo=TermRepository(db))
        finally:
            db.close()

    def get_book(self, project_id: str) -> Book:
        book = self.book_manager.get_book(project_id)
        if book is None:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Project not found: {project_id}")
        return book

    def get_project_ref(self, project_id: str) -> ProjectRef:
        book = self.get_book(project_id)
        return ProjectRef(project_id=book.book_id, name=book.name)

    def get_effective_config_payload(self, project_id: str) -> dict[str, Any]:
        self.get_book(project_id)
        config = self.book_manager.get_book_config(project_id)
        if config is None:
            raise_application_error(
                ApplicationErrorCode.PRECONDITION,
                f"Project {project_id} has no usable configuration.",
                project_id=project_id,
            )
        return dict(config)

    def get_effective_config(self, project_id: str) -> Config:
        book = self.get_book(project_id)
        return Config.from_book(book, self.book_manager.library_root, self.book_manager.registry)

    def get_default_profile(self) -> ConfigProfile | None:
        return self.book_manager.get_default_profile()

    def list_connection_options(self) -> list[tuple[str, str]]:
        return [(profile.profile_id, profile.name) for profile in self.book_manager.list_endpoint_profiles()]

    def submit_task(self, task_type: str, project_id: str, **params: object) -> AcceptedCommand:
        decision = self.task_engine.preflight(task_type, project_id, params, TaskAction.RUN)
        if not decision.allowed:
            raise_blocked_decision(decision, project_id=project_id, task_type=task_type)
        record = self.task_engine.submit_and_start(task_type, project_id, **params)
        self.invalidate_task_activity(project_id)
        return AcceptedCommand(
            command_name=task_type,
            command_id=record.task_id,
            queue_item_id=record.task_id,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text=f"{task_type} queued.",
            ),
        )

    def invalidate_projects(self) -> None:
        self.events.publish(ProjectsInvalidatedEvent())

    def invalidate_setup(self, project_id: str | None = None) -> None:
        self.events.publish(SetupInvalidatedEvent(project_id=project_id))

    def invalidate_queue(self, project_id: str | None = None) -> None:
        self.events.publish(QueueChangedEvent(project_id=project_id))

    def invalidate_workboard(self, project_id: str | None = None) -> None:
        self.events.publish(WorkboardInvalidatedEvent(project_id=project_id))

    def invalidate_document(
        self,
        project_id: str | None,
        document_id: int | None = None,
        *,
        sections: list[DocumentSection] | None = None,
    ) -> None:
        self.events.publish(
            DocumentInvalidatedEvent(
                project_id=project_id,
                document_id=document_id,
                sections=list(sections or []),
            )
        )

    def invalidate_terms(self, project_id: str | None = None, document_id: int | None = None) -> None:
        self.events.publish(TermsInvalidatedEvent(project_id=project_id, document_id=document_id))

    def invalidate_task_activity(self, project_id: str | None = None) -> None:
        self.events.publish_many(
            [
                QueueChangedEvent(project_id=project_id),
                WorkboardInvalidatedEvent(project_id=project_id),
                DocumentInvalidatedEvent(project_id=project_id),
                TermsInvalidatedEvent(project_id=project_id),
                ProjectsInvalidatedEvent(),
            ]
        )


def raise_application_error(
    code: ApplicationErrorCode,
    message: str,
    **details: str | int | float | bool | None,
) -> NoReturn:
    raise ApplicationError(ApplicationErrorPayload(code=code, message=message, details=details))


def blocker_code_for_decision_code(decision_code: str) -> BlockerCode:
    if decision_code in {"blocked_claim_conflict"}:
        return BlockerCode.ALREADY_RUNNING_ELSEWHERE
    if decision_code in {"config_snapshot_unavailable"}:
        return BlockerCode.NEEDS_SETUP
    return BlockerCode.NOTHING_TO_DO


def raise_blocked_decision(decision: Decision, **details: str | int | float | bool | None) -> NoReturn:
    raise BlockedOperationError(
        ApplicationErrorPayload(
            code=ApplicationErrorCode.BLOCKED,
            message=decision.reason or "Operation is blocked.",
            details={"decision_code": decision.code, **details},
        )
    )


def infer_provider_kind(base_url: str | None, model: str | None = None) -> ProviderKind:
    base = (base_url or "").lower()
    model_name = (model or "").lower()
    if "generativelanguage.googleapis.com" in base or model_name.startswith("gemini"):
        return ProviderKind.GEMINI
    if "api.deepseek.com" in base or model_name.startswith("deepseek"):
        return ProviderKind.DEEPSEEK
    if "api.anthropic.com" in base or model_name.startswith("claude"):
        return ProviderKind.ANTHROPIC
    if "api.openai.com" in base or model_name.startswith("gpt") or model_name.startswith("o"):
        return ProviderKind.OPENAI
    return ProviderKind.OPENAI_COMPATIBLE


def infer_capabilities(provider: ProviderKind) -> list[CapabilityCode]:
    if provider is ProviderKind.GEMINI:
        return [
            CapabilityCode.TRANSLATION,
            CapabilityCode.IMAGE_TEXT_READING,
            CapabilityCode.IMAGE_EDITING,
            CapabilityCode.REASONING_AND_REVIEW,
        ]
    if provider is ProviderKind.OPENAI:
        return [
            CapabilityCode.TRANSLATION,
            CapabilityCode.IMAGE_TEXT_READING,
            CapabilityCode.IMAGE_EDITING,
        ]
    if provider is ProviderKind.ANTHROPIC:
        return [CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING]
    if provider is ProviderKind.DEEPSEEK:
        return [CapabilityCode.TRANSLATION]
    return [CapabilityCode.TRANSLATION]


def infer_connection_status(profile: EndpointProfile) -> ConnectionStatus:
    if profile.api_key and profile.base_url and profile.model:
        return ConnectionStatus.READY
    if profile.api_key or profile.base_url or profile.model:
        return ConnectionStatus.PARTIAL
    return ConnectionStatus.UNTESTED


def build_connection_summary(profile: EndpointProfile) -> ConnectionSummary:
    provider = infer_provider_kind(profile.base_url, profile.model)
    return ConnectionSummary(
        connection_id=profile.profile_id,
        display_name=profile.name,
        provider=provider,
        base_url=profile.base_url or None,
        default_model=profile.model or None,
        status=infer_connection_status(profile),
        capabilities=infer_capabilities(provider),
    )


def build_capability_cards(
    connections: list,
    default_routes: list[DefaultRoute],
) -> list[CapabilityCard]:
    route_by_capability = {route.capability: route for route in default_routes}
    cards: list[CapabilityCard] = []
    for capability in CapabilityCode:
        route = route_by_capability.get(capability)
        if route is not None:
            cards.append(
                CapabilityCard(
                    capability=capability,
                    availability=CapabilityAvailability.READY,
                    message=f"Using {route.connection_label}",
                    connection_id=route.connection_id,
                    connection_label=route.connection_label,
                )
            )
            continue
        supporting = [conn for conn in connections if capability in conn.capabilities]
        if supporting:
            cards.append(
                CapabilityCard(
                    capability=capability,
                    availability=CapabilityAvailability.PARTIAL,
                    message="Configured provider available but not routed by default.",
                    connection_id=supporting[0].connection_id,
                    connection_label=supporting[0].display_name,
                )
            )
        else:
            cards.append(
                CapabilityCard(
                    capability=capability,
                    availability=CapabilityAvailability.MISSING,
                    message="No configured provider supports this capability.",
                )
            )
    return cards


def build_default_routes_from_config(config: dict[str, Any]) -> list[DefaultRoute]:
    routes: list[DefaultRoute] = []
    pairs = {
        CapabilityCode.TRANSLATION: config.get("translator_config", {}).get("endpoint_profile"),
        CapabilityCode.IMAGE_TEXT_READING: config.get("ocr_config", {}).get("endpoint_profile"),
        CapabilityCode.IMAGE_EDITING: config.get("image_reembedding_config", {}).get("endpoint_profile"),
        CapabilityCode.REASONING_AND_REVIEW: config.get("review_config", {}).get("endpoint_profile"),
    }
    for capability, connection_id in pairs.items():
        if isinstance(connection_id, str) and connection_id.strip():
            routes.append(
                DefaultRoute(
                    capability=capability,
                    connection_id=connection_id,
                    connection_label=connection_id,
                )
            )
    return routes


def build_workflow_profile_payload(
    *,
    base_config: dict[str, Any] | None,
    routes: list[DefaultRoute],
    target_language: str,
    preset_code: str | None,
) -> dict[str, Any]:
    payload = dict(base_config or {})
    payload["translation_target_language"] = target_language
    if preset_code is not None:
        payload[_UI_PRESET_KEY] = preset_code

    route_map = {route.capability: route.connection_id for route in routes}
    translation_ref = route_map.get(CapabilityCode.TRANSLATION) or _first_route_id(routes)
    ocr_ref = route_map.get(CapabilityCode.IMAGE_TEXT_READING) or translation_ref
    image_edit_ref = route_map.get(CapabilityCode.IMAGE_EDITING) or translation_ref or ocr_ref
    review_ref = route_map.get(CapabilityCode.REASONING_AND_REVIEW) or translation_ref

    payload.setdefault("extractor_config", {})
    payload.setdefault("summarizor_config", {})
    payload.setdefault("glossary_config", {})
    payload.setdefault("translator_config", {})
    payload.setdefault("review_config", {})
    payload.setdefault("ocr_config", {})
    payload.setdefault("image_reembedding_config", {})
    payload.setdefault("manga_translator_config", {})

    for key in ("extractor_config", "summarizor_config", "glossary_config", "translator_config"):
        if translation_ref is not None:
            payload[key]["endpoint_profile"] = translation_ref
    if review_ref is not None:
        payload["review_config"]["endpoint_profile"] = review_ref
    if ocr_ref is not None:
        payload["ocr_config"]["endpoint_profile"] = ocr_ref
        payload["manga_translator_config"]["endpoint_profile"] = ocr_ref
    if image_edit_ref is not None:
        payload["image_reembedding_config"]["endpoint_profile"] = image_edit_ref

    apply_preset_to_payload(payload, preset_code)
    return payload


def apply_preset_to_payload(payload: dict[str, Any], preset_code: str | None) -> None:
    translator_config = payload.setdefault("translator_config", {})
    if preset_code == "fast":
        translator_config["enable_polish"] = False
        translator_config["num_of_chunks_per_llm_call"] = 2
    elif preset_code == "best":
        translator_config["enable_polish"] = True
        translator_config["num_of_chunks_per_llm_call"] = 3
    else:
        translator_config.setdefault("enable_polish", True)
        translator_config.setdefault("num_of_chunks_per_llm_call", 3)


def read_ui_preset(config: dict[str, Any]) -> str | None:
    value = config.get(_UI_PRESET_KEY)
    return str(value) if isinstance(value, str) else None


def _first_route_id(routes: list[DefaultRoute]) -> str | None:
    if not routes:
        return None
    return routes[0].connection_id


def build_project_summary(book_manager: BookManager, book: Book) -> ProjectSummary:
    progress = book_manager.get_book_progress(book.book_id)
    progress_summary: str | None = None
    if progress is not None:
        progress_summary = (
            f"{int(progress['translated_chunks'])}/{int(progress['chunks'])} translated"
            if int(progress.get("chunks", 0) or 0) > 0
            else None
        )
    target_language: str | None = None
    config = book_manager.get_book_config(book.book_id)
    if config is not None and isinstance(config.get("translation_target_language"), str):
        target_language = str(config["translation_target_language"])
    return ProjectSummary(
        project=ProjectRef(project_id=book.book_id, name=book.name),
        target_language=target_language,
        progress_summary=progress_summary,
        modified_at=book.updated_at,
    )


def map_document_type_code(document_type: str | None) -> DocumentTypeCode:
    mapping = {
        "text": DocumentTypeCode.TEXT,
        "pdf": DocumentTypeCode.PDF,
        "epub": DocumentTypeCode.EPUB,
        "scanned_book": DocumentTypeCode.SCANNED_BOOK,
        "manga": DocumentTypeCode.MANGA,
    }
    return mapping.get(str(document_type or ""), DocumentTypeCode.OTHER)


def make_document_ref(document_id: int, label: str, document_type: str | None = None) -> DocumentRef:
    return DocumentRef(
        document_id=document_id,
        order_index=document_id,
        label=label,
        document_type=map_document_type_code(document_type),
    )


def make_blocker(
    code: BlockerCode,
    message: str,
    *,
    target_kind: NavigationTargetKind | None = None,
    project_id: str | None = None,
    document_id: int | None = None,
) -> BlockerInfo:
    target = None
    if target_kind is not None:
        target = NavigationTarget(kind=target_kind, project_id=project_id, document_id=document_id)
    return BlockerInfo(code=code, message=message, target=target)


def queue_status_from_task(record: TaskRecord) -> QueueStatus:
    status = record.status
    if status == "queued":
        return QueueStatus.QUEUED
    if status in {"running", "cancel_requested", "cancelling", "paused"}:
        return QueueStatus.RUNNING
    if status == "failed":
        return QueueStatus.FAILED
    if status == "cancelled":
        return QueueStatus.CANCELLED
    return QueueStatus.DONE


def progress_from_task(record: TaskRecord) -> ProgressInfo | None:
    if record.total_items <= 0 and record.completed_items <= 0:
        return None
    return ProgressInfo(current=record.completed_items, total=record.total_items, label=record.phase)


def related_target_for_task(record: TaskRecord) -> NavigationTarget | None:
    document_id = _single_document_id(record)
    kind: NavigationTargetKind
    if record.task_type == "ocr":
        kind = NavigationTargetKind.DOCUMENT_OCR
    elif record.task_type in {"glossary_extraction", "glossary_translation", "glossary_review", "glossary_export"}:
        kind = NavigationTargetKind.TERMS if document_id is None else NavigationTargetKind.DOCUMENT_TERMS
    elif record.task_type in {"translation_text", "translation_manga", "chunk_retranslation", "batch_translation"}:
        kind = NavigationTargetKind.DOCUMENT_TRANSLATION if document_id is not None else NavigationTargetKind.WORK
    elif record.task_type == "image_reembedding":
        kind = NavigationTargetKind.DOCUMENT_IMAGES if document_id is not None else NavigationTargetKind.WORK
    else:
        kind = NavigationTargetKind.WORK
    return NavigationTarget(kind=kind, project_id=record.book_id, document_id=document_id)


def title_for_task(task_type: str) -> str:
    mapping = {
        "ocr": "Read text from images",
        "glossary_extraction": "Build terms",
        "glossary_translation": "Translate terms",
        "glossary_review": "Review terms",
        "glossary_export": "Export terms",
        "translation_text": "Translate text",
        "translation_manga": "Translate manga",
        "chunk_retranslation": "Retranslate chunk",
        "batch_translation": "Submit async batch",
        "image_reembedding": "Put text back into images",
    }
    return mapping.get(task_type, task_type)


def queue_item_from_record(record: TaskRecord) -> QueueItem:
    actions: list[QueueActionKind] = [QueueActionKind.OPEN_RELATED_ITEM]
    status = queue_status_from_task(record)
    if status in {QueueStatus.QUEUED, QueueStatus.FAILED, QueueStatus.CANCELLED, QueueStatus.DONE}:
        actions.append(QueueActionKind.RUN)
    if status in {QueueStatus.QUEUED, QueueStatus.RUNNING}:
        actions.append(QueueActionKind.CANCEL)
    if status in {QueueStatus.FAILED, QueueStatus.CANCELLED, QueueStatus.DONE}:
        actions.append(QueueActionKind.RETRY)
    if status is not QueueStatus.RUNNING:
        actions.append(QueueActionKind.DELETE)
    return QueueItem(
        queue_item_id=record.task_id,
        title=title_for_task(record.task_type),
        project_id=record.book_id,
        document_id=_single_document_id(record),
        status=status,
        stage=record.phase,
        progress=progress_from_task(record),
        blocker=None,
        error_message=record.last_error,
        related_target=related_target_for_task(record),
        available_actions=actions,
    )


def _single_document_id(record: TaskRecord) -> int | None:
    if not record.document_ids_json:
        return None
    try:
        payload = json.loads(record.document_ids_json)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list) and len(payload) == 1:
        try:
            return int(payload[0])
        except (TypeError, ValueError):
            return None
    return None
