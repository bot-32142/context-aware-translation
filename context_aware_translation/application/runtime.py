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
    SetupWizardMode,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
    default_connection_concurrency,
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
from context_aware_translation.config import Config, infer_async_batch_provider
from context_aware_translation.storage.library.book_manager import BookManager
from context_aware_translation.storage.models.book import Book
from context_aware_translation.storage.models.config_profile import ConfigProfile
from context_aware_translation.storage.models.endpoint_profile import EndpointProfile
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.repositories.task_store import TaskRecord, TaskStore
from context_aware_translation.storage.repositories.term_repository import TermRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.ui.constants import (
    display_target_language_name,
    storage_target_language_name,
)
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from context_aware_translation.adapters.qt.task_engine import TaskEngine
    from context_aware_translation.workflow.tasks.models import Decision
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_DEFAULT_PROFILE_NAME = "app-default-profile"
_UI_SOURCE_PROFILE_ID_KEY = "_ui_source_profile_id"
_MANAGED_CONNECTION_DISPLAY_NAME_KEY = "_ui_display_name"
_MANAGED_CONNECTION_TEMPLATE_KEY = "_wizard_template_key"
_MANAGED_CONNECTION_PREFIXES = ("recommended-",)
_HIDDEN_CONNECTION_KWARG_KEYS = frozenset(
    {
        "provider",
        _MANAGED_CONNECTION_DISPLAY_NAME_KEY,
        _MANAGED_CONNECTION_TEMPLATE_KEY,
    }
)


def _openai_supports_reasoning_effort_none(model: str | None) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("o") or normalized.startswith("gpt-5")


def _wizard_reasoning_effort(
    step_id: WorkflowStepId,
    provider: ProviderKind,
    recommendation_mode: SetupWizardMode,
) -> str | None:
    if provider is ProviderKind.DEEPSEEK:
        return None
    if step_id is WorkflowStepId.GLOSSARY_TRANSLATOR:
        return "low"
    if step_id is WorkflowStepId.OCR:
        return "none"
    if step_id not in {WorkflowStepId.TRANSLATOR, WorkflowStepId.POLISH, WorkflowStepId.MANGA_TRANSLATOR}:
        return None
    if recommendation_mode is SetupWizardMode.BUDGET:
        return "low"
    if recommendation_mode is SetupWizardMode.QUALITY:
        return "high"
    if step_id is WorkflowStepId.POLISH:
        return "medium"
    return "none"


def _wizard_reasoning_kwargs(
    step_id: WorkflowStepId,
    selected: ConnectionDraft | None,
    recommendation_mode: SetupWizardMode,
) -> dict[str, Any] | None:
    if selected is None:
        return None
    reasoning_effort = _wizard_reasoning_effort(step_id, selected.provider, recommendation_mode)
    if reasoning_effort is None:
        return None
    if (
        selected.provider is ProviderKind.OPENAI
        and reasoning_effort == "none"
        and not _openai_supports_reasoning_effort_none(selected.default_model)
    ):
        return None
    return {"reasoning_effort": reasoning_effort}


def _wizard_deepseek_thinking_kwargs(selected: ConnectionDraft | None) -> dict[str, Any] | None:
    if selected is None or selected.provider is not ProviderKind.DEEPSEEK:
        return None
    model = (selected.default_model or "").strip().lower()
    if not model.startswith("deepseek-v4-"):
        return None
    return {"extra_body": {"thinking": {"type": "enabled"}}}


def _wizard_translator_limits(selected: ConnectionDraft | None) -> dict[str, int]:
    if selected is None:
        return {}
    if selected.provider is ProviderKind.DEEPSEEK:
        return {"max_tokens_per_llm_call": 3500, "chunk_size": 1000}
    if selected.provider in {ProviderKind.OPENAI, ProviderKind.ANTHROPIC}:
        return {"max_tokens_per_llm_call": 4000, "chunk_size": 1000}
    if selected.provider is ProviderKind.GEMINI:
        return {"max_tokens_per_llm_call": 3000, "chunk_size": 1000}
    return {}


_WORKFLOW_STEP_LAYOUT: tuple[tuple[WorkflowStepId, str, str | None], ...] = (
    (WorkflowStepId.EXTRACTOR, "Extractor", "extractor_config"),
    (WorkflowStepId.SUMMARIZER, "Summarizer", "summarizor_config"),
    (WorkflowStepId.GLOSSARY_TRANSLATOR, "Glossary translator", "glossary_config"),
    (WorkflowStepId.TRANSLATOR, "Translator", "translator_config"),
    (WorkflowStepId.POLISH, "Polish", "polish_config"),
    (WorkflowStepId.REVIEWER, "Reviewer", "review_config"),
    (WorkflowStepId.OCR, "OCR", "ocr_config"),
    (WorkflowStepId.IMAGE_REEMBEDDING, "Image reembedding", "image_reembedding_config"),
    (WorkflowStepId.MANGA_TRANSLATOR, "Manga translator", "manga_translator_config"),
    (WorkflowStepId.TRANSLATOR_BATCH, "Translator batch", None),
)

_DEFAULT_BATCH_SIZE = 100
_BATCH_PROVIDER_LABELS = {"gemini_ai_studio": "Gemini AI Studio"}


def _coerce_batch_size(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


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
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 2.5 Pro",
            "gemini-2.5-pro",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=300,
        ),
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 3.1 Pro",
            "gemini-3.1-pro",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=300,
        ),
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 2.5 Flash",
            "gemini-2.5-flash",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 2.5 Flash Lite",
            "gemini-2.5-flash-lite",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=120,
        ),
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 3.1 Flash",
            "gemini-3.1-flash",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=300,
        ),
        WizardModelTemplate(
            ProviderKind.GEMINI,
            "Gemini 3 Pro Image Preview",
            "gemini-3-pro-image-preview",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=300,
            concurrency=2,
        ),
    ),
    ProviderKind.OPENAI: (
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-5.4", "gpt-5.4", "https://api.openai.com/v1", timeout=300),
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-4.1", "gpt-4.1", "https://api.openai.com/v1"),
        WizardModelTemplate(ProviderKind.OPENAI, "GPT-4.1 Mini", "gpt-4.1-mini", "https://api.openai.com/v1"),
        WizardModelTemplate(
            ProviderKind.OPENAI, "GPT-4.1 Nano", "gpt-4.1-nano", "https://api.openai.com/v1", timeout=120
        ),
        WizardModelTemplate(ProviderKind.OPENAI, "o4-mini", "o4-mini", "https://api.openai.com/v1", timeout=300),
        WizardModelTemplate(
            ProviderKind.OPENAI, "GPT Image 1", "gpt-image-1", "https://api.openai.com/v1", timeout=300, concurrency=2
        ),
    ),
    ProviderKind.DEEPSEEK: (
        WizardModelTemplate(
            ProviderKind.DEEPSEEK,
            "DeepSeek V4 Flash",
            "deepseek-v4-flash",
            "https://api.deepseek.com",
            concurrency=default_connection_concurrency(ProviderKind.DEEPSEEK),
        ),
        WizardModelTemplate(
            ProviderKind.DEEPSEEK,
            "DeepSeek V4 Pro",
            "deepseek-v4-pro",
            "https://api.deepseek.com",
            timeout=300,
            concurrency=default_connection_concurrency(ProviderKind.DEEPSEEK),
        ),
    ),
    ProviderKind.ANTHROPIC: (
        WizardModelTemplate(
            ProviderKind.ANTHROPIC,
            "Claude Opus 4.6",
            "claude-opus-4-6",
            "https://api.anthropic.com/v1",
            timeout=300,
        ),
        WizardModelTemplate(
            ProviderKind.ANTHROPIC,
            "Claude Sonnet 3.5",
            "claude-3-5-sonnet-latest",
            "https://api.anthropic.com/v1",
            timeout=300,
        ),
        WizardModelTemplate(
            ProviderKind.ANTHROPIC, "Claude Haiku 3.5", "claude-3-5-haiku-latest", "https://api.anthropic.com/v1"
        ),
    ),
}

_STEP_RECOMMENDATION_ORDER: dict[WorkflowStepId, tuple[StepModelPreference, ...]] = {
    WorkflowStepId.EXTRACTOR: (
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-v4-flash"),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash-lite"),
        StepModelPreference(ProviderKind.OPENAI, "o4-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    ),
    WorkflowStepId.SUMMARIZER: (
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-v4-flash"),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash-lite"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-nano"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    ),
    WorkflowStepId.REVIEWER: (
        StepModelPreference(ProviderKind.DEEPSEEK, "deepseek-v4-pro"),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "o4-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    ),
    WorkflowStepId.OCR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-3.1-flash"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    ),
    WorkflowStepId.IMAGE_REEMBEDDING: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-3-pro-image-preview"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-image-1"),
    ),
    WorkflowStepId.MANGA_TRANSLATOR: (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    ),
}


def _glossary_translator_recommendations(recommendation_mode: SetupWizardMode) -> tuple[StepModelPreference, ...]:
    deepseek_model = "deepseek-v4-flash" if recommendation_mode is SetupWizardMode.BUDGET else "deepseek-v4-pro"
    return (
        StepModelPreference(ProviderKind.DEEPSEEK, deepseek_model),
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-flash"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1-mini"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-haiku-latest"),
    )


def _translator_recommendations(recommendation_mode: SetupWizardMode) -> tuple[StepModelPreference, ...]:
    deepseek_model = "deepseek-v4-flash" if recommendation_mode is SetupWizardMode.BUDGET else "deepseek-v4-pro"
    return (
        StepModelPreference(ProviderKind.DEEPSEEK, deepseek_model),
        StepModelPreference(ProviderKind.GEMINI, "gemini-3.1-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-5.4"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-opus-4-6"),
    )


def _polish_recommendations(recommendation_mode: SetupWizardMode) -> tuple[StepModelPreference, ...]:
    deepseek_model = "deepseek-v4-flash" if recommendation_mode is SetupWizardMode.BUDGET else "deepseek-v4-pro"
    return (
        StepModelPreference(ProviderKind.DEEPSEEK, deepseek_model),
        StepModelPreference(ProviderKind.GEMINI, "gemini-3.1-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-5.4"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-opus-4-6"),
    )


def _manga_translator_recommendations(recommendation_mode: SetupWizardMode) -> tuple[StepModelPreference, ...]:
    if recommendation_mode is SetupWizardMode.QUALITY:
        return (
            StepModelPreference(ProviderKind.GEMINI, "gemini-3.1-pro"),
            StepModelPreference(ProviderKind.OPENAI, "o4-mini"),
            StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
        )
    return (
        StepModelPreference(ProviderKind.GEMINI, "gemini-2.5-pro"),
        StepModelPreference(ProviderKind.OPENAI, "gpt-4.1"),
        StepModelPreference(ProviderKind.ANTHROPIC, "claude-3-5-sonnet-latest"),
    )


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
        return AcceptedCommand(
            command_name=task_type,
            command_id=record.task_id,
            queue_item_id=record.task_id,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text=f"{title_for_task(task_type)} queued.",
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


def wizard_connection_key(provider: ProviderKind, model: str | None) -> str | None:
    normalized_model = (model or "").strip()
    if not normalized_model:
        return None
    return f"{provider.value}:{normalized_model}"


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


def managed_connection_key(profile: EndpointProfile) -> str | None:
    stored_key = (profile.kwargs or {}).get(_MANAGED_CONNECTION_TEMPLATE_KEY)
    if isinstance(stored_key, str) and stored_key.strip():
        return stored_key.strip()
    if not is_managed_connection_name(profile.name):
        return None
    return wizard_connection_key(infer_provider_kind(profile.base_url, profile.model), profile.model)


def is_managed_connection(profile: EndpointProfile) -> bool:
    return managed_connection_key(profile) is not None or is_managed_connection_name(profile.name)


def connection_display_name(profile: EndpointProfile) -> str:
    stored_name = (profile.kwargs or {}).get(_MANAGED_CONNECTION_DISPLAY_NAME_KEY)
    if isinstance(stored_name, str) and stored_name.strip():
        return stored_name.strip()
    return public_connection_name(profile.name)


def wizard_connection_key_for_draft(draft: ConnectionDraft) -> str | None:
    return wizard_connection_key(draft.provider, draft.default_model)


def build_connection_summary(profile: EndpointProfile) -> ConnectionSummary:
    provider = infer_provider_kind(profile.base_url, profile.model)
    kwargs_payload = {
        str(key): value for key, value in (profile.kwargs or {}).items() if key not in _HIDDEN_CONNECTION_KWARG_KEYS
    }
    is_managed = is_managed_connection(profile)
    return ConnectionSummary(
        connection_id=profile.profile_id,
        display_name=connection_display_name(profile),
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


def _step_payload_without_routing(step_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in step_payload.items()
        if key not in {"endpoint_profile", "model"} and value is not None
    }


def _batch_provider_label(provider: str) -> str:
    return _BATCH_PROVIDER_LABELS.get(provider, provider)


def _resolved_route_batch_provider(
    route: WorkflowStepRoute | None,
    *,
    connection_base_url_by_id: dict[str, str | None] | None,
) -> str | None:
    if route is None or not route.connection_id:
        return None
    base_url = (connection_base_url_by_id or {}).get(route.connection_id)
    return infer_async_batch_provider(base_url)


def _eligible_pipeline_batch_provider(
    *,
    translator_route: WorkflowStepRoute | None,
    polish_route: WorkflowStepRoute | None,
    connection_base_url_by_id: dict[str, str | None] | None,
) -> str | None:
    translator_provider = _resolved_route_batch_provider(
        translator_route,
        connection_base_url_by_id=connection_base_url_by_id,
    )
    if translator_provider is None:
        return None
    polish_provider = _resolved_route_batch_provider(
        polish_route,
        connection_base_url_by_id=connection_base_url_by_id,
    )
    if polish_provider != translator_provider:
        return None
    return translator_provider


def _build_standard_route(
    *,
    step_id: WorkflowStepId,
    step_label: str,
    step_payload: dict[str, Any],
    connection_name_by_id: dict[str, str],
    connection_model_by_id: dict[str, str | None],
) -> WorkflowStepRoute:
    connection_id = (
        step_payload.get("endpoint_profile") if isinstance(step_payload.get("endpoint_profile"), str) else None
    )
    model = (
        step_payload.get("model") if isinstance(step_payload.get("model"), str) and step_payload.get("model") else None
    )
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


_POLISH_FALLBACK_STEP_CONFIG_KEYS = frozenset({"temperature", "timeout", "max_retries", "concurrency", "kwargs"})


def _build_polish_fallback_route(
    *,
    step_label: str,
    translator_route: WorkflowStepRoute | None,
) -> WorkflowStepRoute:
    if translator_route is None:
        return WorkflowStepRoute(step_id=WorkflowStepId.POLISH, step_label=step_label)
    step_config = {
        str(key): value
        for key, value in translator_route.step_config.items()
        if key in _POLISH_FALLBACK_STEP_CONFIG_KEYS and value is not None
    }
    return WorkflowStepRoute(
        step_id=WorkflowStepId.POLISH,
        step_label=step_label,
        connection_id=translator_route.connection_id,
        connection_label=translator_route.connection_label,
        model=translator_route.model,
        step_config=step_config,
    )


def _build_batch_route(
    *,
    step_label: str,
    translator_route: WorkflowStepRoute | None,
    polish_route: WorkflowStepRoute | None,
    config: dict[str, Any],
    connection_base_url_by_id: dict[str, str | None] | None,
) -> WorkflowStepRoute | None:
    provider = _eligible_pipeline_batch_provider(
        translator_route=translator_route,
        polish_route=polish_route,
        connection_base_url_by_id=connection_base_url_by_id,
    )
    if provider is None:
        return None
    translator_batch_payload = config.get("translator_batch_config")
    polish_batch_payload = config.get("polish_batch_config")
    translator_batch_config = translator_batch_payload if isinstance(translator_batch_payload, dict) else {}
    polish_batch_config = polish_batch_payload if isinstance(polish_batch_payload, dict) else {}
    translator_batch_size = _coerce_batch_size(translator_batch_config.get("batch_size"), _DEFAULT_BATCH_SIZE)
    polish_batch_size = _coerce_batch_size(polish_batch_config.get("batch_size"), translator_batch_size)
    return WorkflowStepRoute(
        step_id=WorkflowStepId.TRANSLATOR_BATCH,
        step_label=step_label,
        connection_id=None,
        connection_label=_batch_provider_label(provider),
        model=None,
        step_config={
            "translator_batch_size": translator_batch_size,
            "polish_batch_size": polish_batch_size,
        },
    )


def _build_standard_step_payload(route: WorkflowStepRoute) -> dict[str, Any]:
    payload: dict[str, Any] = {str(key): value for key, value in route.step_config.items() if value is not None}
    if route.connection_id:
        payload["endpoint_profile"] = route.connection_id
    if route.model:
        payload["model"] = route.model
    if route.step_id is WorkflowStepId.IMAGE_REEMBEDDING:
        backend = _infer_image_backend(route)
        if backend is not None:
            payload["backend"] = backend
    return payload


def _build_batch_step_payload(route: WorkflowStepRoute) -> dict[str, Any]:
    return {str(key): value for key, value in route.step_config.items() if value is not None}


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
    connection_base_url_by_id: dict[str, str | None] | None = None,
    is_default: bool = False,
) -> WorkflowProfileDetail:
    step_config_map = _workflow_step_config_map(config)
    routes: list[WorkflowStepRoute] = []
    translator_route: WorkflowStepRoute | None = None
    polish_route: WorkflowStepRoute | None = None
    for step_id, label, _config_key in _WORKFLOW_STEP_LAYOUT:
        if step_id is WorkflowStepId.TRANSLATOR_BATCH:
            batch_route = _build_batch_route(
                step_label=label,
                translator_route=translator_route,
                polish_route=polish_route,
                config=config,
                connection_base_url_by_id=connection_base_url_by_id,
            )
            if batch_route is not None:
                routes.append(batch_route)
            continue
        if step_id is WorkflowStepId.POLISH and not step_config_map.get(step_id):
            route = _build_polish_fallback_route(step_label=label, translator_route=translator_route)
            polish_route = route
            routes.append(route)
            continue
        route = _build_standard_route(
            step_id=step_id,
            step_label=label,
            step_payload=step_config_map.get(step_id, {}),
            connection_name_by_id=connection_name_by_id,
            connection_model_by_id=connection_model_by_id,
        )
        if step_id is WorkflowStepId.TRANSLATOR:
            translator_route = route
        elif step_id is WorkflowStepId.POLISH:
            polish_route = route
        routes.append(route)

    target_language = (
        display_target_language_name(str(config.get("translation_target_language") or "English")) or "English"
    )
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
    payload["translation_target_language"] = (
        storage_target_language_name(profile.target_language) or profile.target_language
    )
    if source_profile_id:
        payload[_UI_SOURCE_PROFILE_ID_KEY] = source_profile_id
    else:
        payload.pop(_UI_SOURCE_PROFILE_ID_KEY, None)

    route_map = {route.step_id: route for route in profile.routes}
    for step_id, _label, config_key in _WORKFLOW_STEP_LAYOUT:
        route = route_map.get(step_id)
        if step_id is WorkflowStepId.TRANSLATOR_BATCH:
            batch_payload = _build_batch_step_payload(route) if route is not None else {}
            translator_batch_size = batch_payload.get("translator_batch_size")
            polish_batch_size = batch_payload.get("polish_batch_size")
            if translator_batch_size is not None:
                payload["translator_batch_config"] = {"batch_size": int(translator_batch_size)}
            else:
                payload.pop("translator_batch_config", None)
            if polish_batch_size is not None:
                payload["polish_batch_config"] = {"batch_size": int(polish_batch_size)}
            else:
                payload.pop("polish_batch_config", None)
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


def _recommendations_for_step(
    step_id: WorkflowStepId,
    recommendation_mode: SetupWizardMode,
) -> tuple[StepModelPreference, ...]:
    if step_id is WorkflowStepId.GLOSSARY_TRANSLATOR:
        return _glossary_translator_recommendations(recommendation_mode)
    if step_id is WorkflowStepId.TRANSLATOR:
        return _translator_recommendations(recommendation_mode)
    if step_id is WorkflowStepId.POLISH:
        return _polish_recommendations(recommendation_mode)
    if step_id is WorkflowStepId.MANGA_TRANSLATOR:
        return _manga_translator_recommendations(recommendation_mode)
    return _STEP_RECOMMENDATION_ORDER.get(step_id, ())


def _recommended_step_route(
    step_id: WorkflowStepId,
    label: str,
    drafts: list[ConnectionDraft],
    recommendation_mode: SetupWizardMode,
) -> WorkflowStepRoute:
    if step_id is WorkflowStepId.TRANSLATOR_BATCH:
        return WorkflowStepRoute(step_id=step_id, step_label=label)

    selected = None
    for preference in _recommendations_for_step(step_id, recommendation_mode):
        selected = _recommended_connection_by_model(drafts, preference)
        if selected is not None:
            break

    step_config: dict[str, Any] = {}
    llm_kwargs: dict[str, Any] = {}
    deepseek_thinking_kwargs = _wizard_deepseek_thinking_kwargs(selected)
    reasoning_kwargs = _wizard_reasoning_kwargs(step_id, selected, recommendation_mode)
    if step_id is WorkflowStepId.EXTRACTOR:
        step_config["max_gleaning"] = 1
    if step_id is WorkflowStepId.TRANSLATOR:
        step_config.update(_wizard_translator_limits(selected))
    if deepseek_thinking_kwargs is not None:
        llm_kwargs.update(deepseek_thinking_kwargs)
    if reasoning_kwargs is not None:
        llm_kwargs.update(reasoning_kwargs)
    if llm_kwargs:
        step_config["kwargs"] = llm_kwargs
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


def _recommended_batch_route(
    *,
    label: str,
    curated_drafts: list[ConnectionDraft],
    routes: list[WorkflowStepRoute],
) -> WorkflowStepRoute | None:
    route_map = {route.step_id: route for route in routes}
    translator_route = route_map.get(WorkflowStepId.TRANSLATOR)
    polish_route = route_map.get(WorkflowStepId.POLISH)
    draft_base_urls = {draft.display_name: draft.base_url for draft in curated_drafts}
    provider = _eligible_pipeline_batch_provider(
        translator_route=translator_route,
        polish_route=polish_route,
        connection_base_url_by_id=draft_base_urls,
    )
    if provider is None:
        return None
    return WorkflowStepRoute(
        step_id=WorkflowStepId.TRANSLATOR_BATCH,
        step_label=label,
        connection_id=None,
        connection_label=_batch_provider_label(provider),
        model=None,
        step_config={
            "translator_batch_size": _DEFAULT_BATCH_SIZE,
            "polish_batch_size": _DEFAULT_BATCH_SIZE,
        },
    )


def recommended_workflow_profile_from_drafts(
    drafts: list[ConnectionDraft],
    *,
    profile_id: str = "recommended",
    name: str = "Recommended",
    target_language: str = "English",
    recommendation_mode: SetupWizardMode = SetupWizardMode.BALANCED,
) -> WorkflowProfileDetail:
    curated_drafts = expand_wizard_connection_drafts(drafts)
    routes: list[WorkflowStepRoute] = []
    for step_id, label, _config_key in _WORKFLOW_STEP_LAYOUT:
        if step_id is WorkflowStepId.TRANSLATOR_BATCH:
            batch_route = _recommended_batch_route(label=label, curated_drafts=curated_drafts, routes=routes)
            if batch_route is not None:
                routes.append(batch_route)
            continue
        routes.append(_recommended_step_route(step_id, label, curated_drafts, recommendation_mode))
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
        target_language = display_target_language_name(str(config["translation_target_language"]))
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
        "subtitle": DocumentTypeCode.SUBTITLE,
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
    elif record.task_type == "translate_and_export":
        phase = record.phase or ""
        if phase == "ocr":
            kind = NavigationTargetKind.DOCUMENT_OCR
        elif phase in {"extract_terms", "term_memory", "rare_filter", "review", "translate_glossary"}:
            kind = NavigationTargetKind.DOCUMENT_TERMS
        elif phase in {
            "translate_chunks",
            "prepare",
            "translation_submit",
            "translation_poll",
            "translation_validate",
            "translation_fallback",
            "polish_submit",
            "polish_poll",
            "polish_validate",
            "polish_fallback",
            "apply",
        }:
            kind = NavigationTargetKind.DOCUMENT_TRANSLATION
        elif phase == "reembed":
            kind = NavigationTargetKind.DOCUMENT_IMAGES
        elif phase == "export":
            kind = NavigationTargetKind.DOCUMENT_EXPORT
        else:
            kind = NavigationTargetKind.WORK
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
        "translate_and_export": "Translate and Export",
    }
    return mapping.get(task_type, task_type)


def queue_item_from_record(record: TaskRecord) -> QueueItem:
    status = queue_status_from_task(record)
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
        available_actions=_available_actions_for_task(record, status),
    )


def _available_actions_for_task(record: TaskRecord, status: QueueStatus) -> list[QueueActionKind]:
    actions: list[QueueActionKind] = [QueueActionKind.OPEN_RELATED_ITEM]
    raw_status = record.status

    if status in {QueueStatus.QUEUED, QueueStatus.RUNNING}:
        if status is QueueStatus.QUEUED:
            actions.append(QueueActionKind.RUN)
        actions.append(QueueActionKind.CANCEL)
        return actions

    if raw_status in {"failed", "cancelled", "completed_with_errors"}:
        actions.extend((QueueActionKind.RUN, QueueActionKind.RETRY, QueueActionKind.DELETE))
        return actions

    actions.append(QueueActionKind.DELETE)
    return actions


def _single_document_id(record: TaskRecord) -> int | None:
    if not record.document_ids_json:
        return _document_id_from_payload(record.payload_json)
    try:
        payload = json.loads(record.document_ids_json)
    except json.JSONDecodeError:
        return _document_id_from_payload(record.payload_json)
    if isinstance(payload, list) and len(payload) == 1:
        try:
            return int(payload[0])
        except (TypeError, ValueError):
            return _document_id_from_payload(record.payload_json)
    return _document_id_from_payload(record.payload_json)


def _document_id_from_payload(payload_json: str | None) -> int | None:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_document_id = payload.get("document_id")
    if raw_document_id is not None:
        try:
            return int(raw_document_id)
        except (TypeError, ValueError):
            return None
    raw_document_ids = payload.get("document_ids")
    if isinstance(raw_document_ids, list) and len(raw_document_ids) == 1:
        try:
            return int(raw_document_ids[0])
        except (TypeError, ValueError):
            return None
    return None
