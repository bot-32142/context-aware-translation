from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from context_aware_translation.application.contracts.app_setup import (
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
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
_UI_SOURCE_PROFILE_ID_KEY = "_ui_source_profile_id"
_MANAGED_CONNECTION_PREFIXES = ("recommended-", "system-default-")

_WORKFLOW_STEP_LAYOUT: tuple[tuple[WorkflowStepId, str, str | None], ...] = (
    (WorkflowStepId.EXTRACTOR, "Extractor", "extractor_config"),
    (WorkflowStepId.SUMMARIZER, "Summarizer", "summarizor_config"),
    (WorkflowStepId.GLOSSARY_TRANSLATOR, "Glossary translator", "glossary_config"),
    (WorkflowStepId.TRANSLATOR, "Translator", "translator_config"),
    (WorkflowStepId.REVIEWER, "Reviewer", "review_config"),
    (WorkflowStepId.OCR, "OCR", "ocr_config"),
    (WorkflowStepId.IMAGE_REEMBEDDING, "Image reembedding", "image_reembedding_config"),
    (WorkflowStepId.MANGA_TRANSLATOR, "Manga translator", "manga_translator_config"),
    (WorkflowStepId.TRANSLATOR_BATCH, "Translator batch", None),
)


@dataclass(frozen=True)
class WizardModelTemplate:
    provider: ProviderKind
    display_name: str
    model: str
    base_url: str
    timeout: int = 180
    max_retries: int = 3
    concurrency: int = 5


@dataclass(frozen=True)
class StepModelPreference:
    provider: ProviderKind
    model: str


_WIZARD_MODEL_CATALOG: dict[ProviderKind, tuple[WizardModelTemplate, ...]] = {
    ProviderKind.GEMINI: (
        WizardModelTemplate(ProviderKind.GEMINI, "Gemini 2.5 Pro", "gemini-2.5-pro", "https://generativelanguage.googleapis.com/v1beta/openai/", timeout=300),
        WizardModelTemplate(ProviderKind.GEMINI, "Gemini 2.5 Flash", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        WizardModelTemplate(ProviderKind.GEMINI, "Gemini 2.5 Flash Lite", "gemini-2.5-flash-lite", "https://generativelanguage.googleapis.com/v1beta/openai/", timeout=120),
        WizardModelTemplate(ProviderKind.GEMINI, "Gemini 3 Flash Preview", "gemini-3-flash-preview", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        WizardModelTemplate(ProviderKind.GEMINI, "Gemini 3.1 Flash Image Preview", "gemini-3.1-flash-image-preview", "https://generativelanguage.googleapis.com/v1beta/openai/", timeout=300, concurrency=2),
    ),
    ProviderKind.OPENAI: (
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-4.1", "gpt-4.1", "https://api.openai.com/v1"),
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-4.1 Mini", "gpt-4.1-mini", "https://api.openai.com/v1"),
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-4.1 Nano", "gpt-4.1-nano", "https://api.openai.com/v1", timeout=120),
        WizardModelTemplate(ProviderKind.OPENAI, "o4-mini", "o4-mini", "https://api.openai.com/v1", timeout=300),
        WizardModelTemplate(ProviderKind.OPENAI, "GPT Image 1", "gpt-image-1", "https://api.openai.com/v1", timeout=300, concurrency=2),
    ),
    ProviderKind.DEEPSEEK: (
        WizardModelTemplate(ProviderKind.DEEPSEEK, "DeepSeek Chat", "deepseek-chat", "https://api.deepseek.com"),
        WizardModelTemplate(ProviderKind.DEEPSEEK, "DeepSeek Reasoner", "deepseek-reasoner", "https://api.deepseek.com", timeout=300),
    ),
    ProviderKind.ANTHROPIC: (
        WizardModelTemplate(ProviderKind.ANTHROPIC, "Claude Sonnet 3.5", "claude-3-5-sonnet-latest", "https://api.anthropic.com/v1", timeout=300),
        WizardModelTemplate(ProviderKind.ANTHROPIC, "Claude Haiku 3.5", "claude-3-5-haiku-latest", "https://api.anthropic.com/v1"),
    ),
}

_STEP_RECOMMENDATION_ORDER: dict[WorkflowStepId, tuple[StepModelPreference, ...]] = {
    WorkflowStepId.EXTRACTOR: (
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-chat"),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash-lite"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-nano"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    ),
    WorkflowStepId.SUMMARIZER: (
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-chat"),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash-lite"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-nano"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    ),
    WorkflowStepId.GLOSSARY_TRANSLATOR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash"),
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-chat"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    ),
    WorkflowStepId.TRANSLATOR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-chat"),
    ),
    WorkflowStepId.REVIEWER: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "o4-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-reasoner"),
    ),
    WorkflowStepId.OCR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-3-flash-preview"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    ),
    WorkflowStepId.IMAGE_REEMBEDDING: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-3.1-flash-image-preview"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-image-1"),
    ),
    WorkflowStepId.MANGA_TRANSLATOR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    ),
}


@dataclass(frozen=True)
class DefaultRouteInfo:
    capability: CapabilityCode
    connection_id: str | None = None


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


def is_managed_connection_name(name: str) -> bool:
    normalized = name.strip().lower()
    return any(normalized.startswith(prefix) for prefix in _MANAGED_CONNECTION_PREFIXES)


def public_connection_name(name: str) -> str:
    stripped = name.strip()
    lowered = stripped.lower()
    for prefix in _MANAGED_CONNECTION_PREFIXES:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :]
    return stripped


def build_connection_summary(profile: EndpointProfile) -> ConnectionSummary:
    provider = infer_provider_kind(profile.base_url, profile.model)
    kwargs_payload = {str(key): value for key, value in (profile.kwargs or {}).items() if key != "provider"}
    is_managed = is_managed_connection_name(profile.name)
    return ConnectionSummary(
        connection_id=profile.profile_id,
        display_name=public_connection_name(profile.name),
        is_managed=is_managed,
        provider=provider,
        description=profile.description,
        base_url=profile.base_url or None,
        default_model=profile.model or None,
        temperature=profile.temperature,
        timeout=profile.timeout,
        max_retries=profile.max_retries,
        concurrency=profile.concurrency,
        token_limit=profile.token_limit,
        input_token_limit=profile.input_token_limit,
        output_token_limit=profile.output_token_limit,
        tokens_used=profile.tokens_used,
        input_tokens_used=profile.input_tokens_used,
        output_tokens_used=profile.output_tokens_used,
        cached_input_tokens_used=profile.cached_input_tokens_used,
        uncached_input_tokens_used=profile.uncached_input_tokens_used,
        custom_parameters_json=(json.dumps(kwargs_payload, indent=2, ensure_ascii=False) if kwargs_payload else None),
        status=infer_connection_status(profile),
        capabilities=infer_capabilities(provider),
    )

def build_default_routes_from_config(config: dict[str, Any]) -> list[DefaultRouteInfo]:
    capability_step_map: tuple[tuple[CapabilityCode, WorkflowStepId], ...] = (
        (CapabilityCode.TRANSLATION, WorkflowStepId.TRANSLATOR),
        (CapabilityCode.IMAGE_TEXT_READING, WorkflowStepId.OCR),
        (CapabilityCode.IMAGE_EDITING, WorkflowStepId.IMAGE_REEMBEDDING),
        (CapabilityCode.REASONING_AND_REVIEW, WorkflowStepId.REVIEWER),
    )
    routes: list[DefaultRouteInfo] = []
    step_config_map = _workflow_step_config_map(config)
    for capability, step_id in capability_step_map:
        step_config = step_config_map.get(step_id, {})
        connection_id = (
            step_config.get("endpoint_profile") if isinstance(step_config.get("endpoint_profile"), str) else None
        )
        routes.append(DefaultRouteInfo(capability=capability, connection_id=connection_id))
    return routes


def _workflow_step_config_map(config: dict[str, Any]) -> dict[WorkflowStepId, dict[str, Any]]:
    return {
        step_id: (config.get(config_key) if config_key is not None else None) or {}
        for step_id, _label, config_key in _WORKFLOW_STEP_LAYOUT
    }


def read_source_profile_id(config: dict[str, Any]) -> str | None:
    value = config.get(_UI_SOURCE_PROFILE_ID_KEY)
    return str(value) if isinstance(value, str) and value.strip() else None


def _step_payload_without_routing(step_payload: dict[str, Any]) -> dict[str, bool | int | float | str | None]:
    return {
        str(key): value
        for key, value in step_payload.items()
        if key not in {"endpoint_profile", "model"} and value is not None
    }


def _build_standard_route(
    *,
    step_id: WorkflowStepId,
    step_label: str,
    step_payload: dict[str, Any],
    connection_name_by_id: dict[str, str],
    connection_model_by_id: dict[str, str | None],
) -> WorkflowStepRoute:
    connection_id = step_payload.get("endpoint_profile") if isinstance(step_payload.get("endpoint_profile"), str) else None
    model = step_payload.get("model") if isinstance(step_payload.get("model"), str) and step_payload.get("model") else None
    if model is None and connection_id is not None:
        model = connection_model_by_id.get(connection_id)
    return WorkflowStepRoute(
        step_id=step_id,
        step_label=step_label,
        connection_id=connection_id,
        connection_label=(connection_name_by_id.get(connection_id, connection_id) if connection_id else None),
        model=model,
        step_config=_step_payload_without_routing(step_payload),
    )


def _build_batch_route(step_label: str, config: dict[str, Any]) -> WorkflowStepRoute:
    batch_payload = config.get("translator_batch_config")
    batch_config = batch_payload if isinstance(batch_payload, dict) else {}
    return WorkflowStepRoute(
        step_id=WorkflowStepId.TRANSLATOR_BATCH,
        step_label=step_label,
        connection_id=None,
        connection_label=(str(batch_config.get("provider") or "Direct batch config") if batch_config else None),
        model=(str(batch_config.get("model") or "") or None),
        step_config={str(key): value for key, value in batch_config.items() if key != "model" and value is not None},
    )


def _build_standard_step_payload(route: WorkflowStepRoute) -> dict[str, bool | int | float | str | None]:
    payload: dict[str, bool | int | float | str | None] = {
        str(key): value for key, value in route.step_config.items() if value is not None
    }
    if route.connection_id:
        payload["endpoint_profile"] = route.connection_id
    if route.model:
        payload["model"] = route.model
    if route.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
        backend = _infer_image_backend(route)
        if backend is not None:
            payload["backend"] = backend
    return payload


def _build_batch_step_payload(route: WorkflowStepRoute) -> dict[str, bool | int | float | str | None]:
    payload: dict[str, bool | int | float | str | None] = {
        str(key): value for key, value in route.step_config.items() if value is not None
    }
    if route.model:
        payload["model"] = route.model
    return payload


def _infer_image_backend(route: WorkflowStepRoute) -> str | None:
    configured = route.step_config.get("backend")
    if isinstance(configured, str) and configured.strip():
        return configured
    model_name = (route.model or "").lower()
    connection_name = (route.connection_label or route.connection_id or "").lower()
    if model_name.startswith("gemini") or "gemini" in connection_name:
        return "gemini"
    if model_name.startswith("qwen") or "qwen" in connection_name or "dashscope" in connection_name:
        return "qwen"
    if model_name:
        return "openai"
    return None


def build_workflow_profile_detail(
    *,
    profile_id: str,
    name: str,
    kind: WorkflowProfileKind,
    config: dict[str, Any],
    connection_name_by_id: dict[str, str],
    connection_model_by_id: dict[str, str | None],
    is_default: bool = False,
) -> WorkflowProfileDetail:
    step_config_map = _workflow_step_config_map(config)
    routes = [
        _build_batch_route(label, config)
        if step_id is WorkflowStepId.TRANSLATOR_BATCH
        else _build_standard_route(
            step_id=step_id,
            step_label=label,
            step_payload=step_config_map.get(step_id, {}),
            connection_name_by_id=connection_name_by_id,
            connection_model_by_id=connection_model_by_id,
        )
        for step_id, label, _config_key in _WORKFLOW_STEP_LAYOUT
    ]

    target_language = str(config.get("translation_target_language") or "English")
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=kind,
        target_language=target_language,
        routes=routes,
        is_default=is_default,
    )


def build_workflow_profile_payload(
    *,
    base_config: dict[str, Any] | None,
    profile: WorkflowProfileDetail,
    source_profile_id: str | None = None,
) -> dict[str, Any]:
    payload = dict(base_config or {})
    payload["translation_target_language"] = profile.target_language
    if source_profile_id:
        payload[_UI_SOURCE_PROFILE_ID_KEY] = source_profile_id
    else:
        payload.pop(_UI_SOURCE_PROFILE_ID_KEY, None)

    route_map = {route.step_id: route for route in profile.routes}
    for step_id, _label, config_key in _WORKFLOW_STEP_LAYOUT:
        route = route_map.get(step_id)
        if step_id is WorkflowStepId.TRANSLATOR_BATCH:
            batch_payload = _build_batch_step_payload(route) if route is not None else {}
            if batch_payload:
                payload["translator_batch_config"] = batch_payload
            else:
                payload.pop("translator_batch_config", None)
            continue
        if config_key is None:
            continue
        next_step_payload = _build_standard_step_payload(route) if route is not None else {}
        if next_step_payload:
            payload[config_key] = next_step_payload
        else:
            payload.pop(config_key, None)
    return payload


def expand_wizard_connection_drafts(seed_drafts: list[ConnectionDraft]) -> list[ConnectionDraft]:
    expanded: list[ConnectionDraft] = []
    for seed in seed_drafts:
        templates = _WIZARD_MODEL_CATALOG.get(seed.provider)
        if not templates:
            expanded.append(seed)
            continue
        for template in templates:
            expanded.append(
                ConnectionDraft(
                    display_name=f"recommended-{template.display_name}",
                    provider=template.provider,
                    description=seed.description,
                    api_key=seed.api_key,
                    base_url=template.base_url,
                    default_model=template.model,
                    temperature=seed.temperature,
                    timeout=template.timeout,
                    max_retries=template.max_retries,
                    concurrency=template.concurrency,
                    token_limit=seed.token_limit,
                    input_token_limit=seed.input_token_limit,
                    output_token_limit=seed.output_token_limit,
                    custom_parameters_json=seed.custom_parameters_json,
                )
            )
    return expanded


def _recommended_connection_by_model(
    drafts: list[ConnectionDraft],
    preference: StepModelPreference,
) -> ConnectionDraft | None:
    return next(
        (
            draft
            for draft in drafts
            if draft.provider is preference.provider and (draft.default_model or "") == preference.model
        ),
        None,
    )


def _recommended_step_route(
    step_id: WorkflowStepId,
    label: str,
    drafts: list[ConnectionDraft],
) -> WorkflowStepRoute:
    if step_id is WorkflowStepId.TRANSLATOR_BATCH:
        gemini_batch = _recommended_connection_by_model(
            drafts, StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro")
        ) or _recommended_connection_by_model(
            drafts, StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash")
        ) or _recommended_connection_by_model(
            drafts, StepModelPreference(ProviderKind.GEMINI, "gemini-3-flash-preview")
        ) or _recommended_connection_by_model(
            drafts, StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash-lite")
        )
        if gemini_batch is None:
            return WorkflowStepRoute(step_id=step_id, step_label=label)
        return WorkflowStepRoute(
            step_id=step_id,
            step_label=label,
            connection_id=None,
            connection_label="Gemini AI Studio",
            model=gemini_batch.default_model,
            step_config={
                "provider": "gemini_ai_studio",
                "api_key": gemini_batch.api_key or "",
                "batch_size": 100,
                "thinking_mode": "auto",
            },
        )

    selected = None
    for preference in _STEP_RECOMMENDATION_ORDER.get(step_id, ()):
        selected = _recommended_connection_by_model(drafts, preference)
        if selected is not None:
            break

    step_config: dict[str, bool | int | float | str | None] = {}
    if step_id is WorkflowStepId.IMAGE_REEMBEDDING and selected is not None:
        if selected.provider is ProviderKind.GEMINI:
            step_config["backend"] = "gemini"
        elif selected.provider is ProviderKind.OPENAI:
            step_config["backend"] = "openai"

    return WorkflowStepRoute(
        step_id=step_id,
        step_label=label,
        connection_id=selected.display_name if selected is not None else None,
        connection_label=public_connection_name(selected.display_name) if selected is not None else None,
        model=selected.default_model if selected is not None else None,
        step_config=step_config,
    )


def recommended_workflow_profile_from_drafts(
    drafts: list[ConnectionDraft],
    *,
    profile_id: str = "recommended",
    name: str = "Recommended",
    target_language: str = "English",
) -> WorkflowProfileDetail:
    curated_drafts = expand_wizard_connection_drafts(drafts)
    routes = [
        _recommended_step_route(step_id, label, curated_drafts)
        for step_id, label, _config_key in _WORKFLOW_STEP_LAYOUT
    ]
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=WorkflowProfileKind.SHARED,
        target_language=target_language,
        routes=routes,
        is_default=True,
    )


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
