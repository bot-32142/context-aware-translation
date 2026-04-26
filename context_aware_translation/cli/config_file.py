from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

from context_aware_translation.application.contracts.app_setup import ConnectionDraft, WorkflowProfileDetail
from context_aware_translation.application.runtime import build_workflow_profile_payload
from context_aware_translation.config import EndpointProfile, ensure_valid_persisted_config_payload

from .output import EXIT_USAGE, CliError

CONFIG_ENV_VAR = "CAT_CONFIG"
LOCAL_CONFIG_NAMES = ("cat.yaml", "cat.yml", ".cat.yaml", ".cat.yml")


STARTER_CONFIG = """# Context-Aware Translation CLI config
version: 1
default_workflow_profile: balanced_deepseek

connections:
  deepseek_flash:
    display_name: DeepSeek V4 Flash
    provider: deepseek
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com
    default_model: deepseek-v4-flash
    temperature: 0
    timeout: 180
    max_retries: 3
    concurrency: 15

  deepseek_pro:
    display_name: DeepSeek V4 Pro
    provider: deepseek
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com
    default_model: deepseek-v4-pro
    temperature: 0
    timeout: 300
    max_retries: 3
    concurrency: 15

workflow_profiles:
  balanced_deepseek:
    profile_id: balanced_deepseek
    name: Balanced DeepSeek
    kind: shared
    target_language: English
    routes:
      - step_id: extractor
        step_label: Extractor
        connection_id: deepseek_flash
        model: deepseek-v4-flash
        step_config:
          max_gleaning: 1
          kwargs:
            extra_body:
              thinking:
                type: enabled
      - step_id: summarizer
        step_label: Summarizer
        connection_id: deepseek_flash
        model: deepseek-v4-flash
        step_config:
          kwargs:
            extra_body:
              thinking:
                type: enabled
      - step_id: glossary_translator
        step_label: Glossary translator
        connection_id: deepseek_pro
        model: deepseek-v4-pro
        step_config:
          kwargs:
            extra_body:
              thinking:
                type: enabled
      - step_id: translator
        step_label: Translator
        connection_id: deepseek_pro
        model: deepseek-v4-pro
        step_config:
          chunk_size: 1000
          max_tokens_per_llm_call: 3500
          strip_epub_ruby: true
          kwargs:
            extra_body:
              thinking:
                type: enabled
      - step_id: polish
        step_label: Polish
        connection_id: deepseek_pro
        model: deepseek-v4-pro
        step_config:
          kwargs:
            extra_body:
              thinking:
                type: enabled
      - step_id: reviewer
        step_label: Reviewer
        connection_id: deepseek_pro
        model: deepseek-v4-pro
        step_config:
          kwargs:
            extra_body:
              thinking:
                type: enabled
"""


@dataclass(frozen=True)
class ResolvedCliConfig:
    path: Path
    profile_key: str
    custom_config: dict[str, Any]


def default_config_path() -> Path:
    return Path(user_config_dir("ContextAwareTranslation", appauthor=False)) / "cli.yaml"


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def find_local_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for parent in (current, *current.parents):
        for name in LOCAL_CONFIG_NAMES:
            candidate = parent / name
            if candidate.exists():
                return candidate
    return None


def resolve_config_path(explicit_path: str | None = None, *, require_exists: bool = False) -> Path:
    if explicit_path:
        path = _normalize_path(explicit_path)
    elif os.environ.get(CONFIG_ENV_VAR):
        path = _normalize_path(os.environ[CONFIG_ENV_VAR])
    else:
        path = find_local_config() or default_config_path()

    if require_exists and not path.exists():
        raise CliError(
            "config_not_found",
            f"Config file not found: {path}",
            exit_code=EXIT_USAGE,
            details={"path": str(path)},
        )
    return path


def write_starter_config(path: Path, *, force: bool = False) -> None:
    if path.exists() and not force:
        raise CliError(
            "config_exists",
            f"Config file already exists: {path}",
            exit_code=EXIT_USAGE,
            details={"path": str(path)},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER_CONFIG, encoding="utf-8")


def load_cli_config(path: Path) -> ResolvedCliConfig:
    if not path.exists():
        raise CliError(
            "config_not_found",
            f"Config file not found: {path}",
            exit_code=EXIT_USAGE,
            details={"path": str(path)},
        )
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise CliError("invalid_config", "Config file must contain a mapping.", exit_code=EXIT_USAGE)
    version = raw.get("version")
    if version != 1:
        raise CliError("invalid_config", "Config version must be 1.", exit_code=EXIT_USAGE)

    connections_payload = raw.get("connections")
    if not isinstance(connections_payload, dict) or not connections_payload:
        raise CliError("invalid_config", "Config must define at least one connection.", exit_code=EXIT_USAGE)
    endpoint_profiles = _endpoint_profiles_from_connections(connections_payload)

    workflow_profiles = raw.get("workflow_profiles")
    if not isinstance(workflow_profiles, dict) or not workflow_profiles:
        raise CliError("invalid_config", "Config must define at least one workflow profile.", exit_code=EXIT_USAGE)
    profile_key = str(raw.get("default_workflow_profile") or "").strip()
    if not profile_key:
        raise CliError("invalid_config", "default_workflow_profile is required.", exit_code=EXIT_USAGE)
    profile_payload = workflow_profiles.get(profile_key)
    if not isinstance(profile_payload, dict):
        raise CliError(
            "invalid_config",
            f"Workflow profile not found: {profile_key}",
            exit_code=EXIT_USAGE,
            details={"profile": profile_key},
        )

    profile = WorkflowProfileDetail.model_validate(profile_payload)
    _validate_route_connections(profile, endpoint_profiles)
    custom_config = build_workflow_profile_payload(base_config=None, profile=profile)
    custom_config["endpoint_profiles"] = {
        connection_id: endpoint_profile.to_dict() for connection_id, endpoint_profile in endpoint_profiles.items()
    }
    ensure_valid_persisted_config_payload(custom_config)
    return ResolvedCliConfig(path=path, profile_key=profile_key, custom_config=custom_config)


def _endpoint_profiles_from_connections(payload: dict[Any, Any]) -> dict[str, EndpointProfile]:
    profiles: dict[str, EndpointProfile] = {}
    for raw_connection_id, raw_connection in payload.items():
        connection_id = str(raw_connection_id).strip()
        if not connection_id:
            raise CliError("invalid_config", "Connection IDs must not be empty.", exit_code=EXIT_USAGE)
        if not isinstance(raw_connection, dict):
            raise CliError(
                "invalid_config",
                f"Connection {connection_id!r} must be a mapping.",
                exit_code=EXIT_USAGE,
                details={"connection_id": connection_id},
            )
        connection_payload = dict(raw_connection)
        api_key_env = _optional_str(connection_payload.pop("api_key_env", None))
        api_key = _optional_str(connection_payload.get("api_key"))
        if api_key and api_key_env:
            raise CliError(
                "invalid_config",
                f"Connection {connection_id!r} cannot set both api_key and api_key_env.",
                exit_code=EXIT_USAGE,
                details={"connection_id": connection_id},
            )
        if api_key_env and not os.environ.get(api_key_env):
            raise CliError(
                "missing_api_key_env",
                f"Environment variable {api_key_env!r} is required by connection {connection_id!r}.",
                exit_code=EXIT_USAGE,
                details={"connection_id": connection_id, "env": api_key_env},
            )
        if not api_key and not api_key_env:
            raise CliError(
                "invalid_config",
                f"Connection {connection_id!r} must set api_key or api_key_env.",
                exit_code=EXIT_USAGE,
                details={"connection_id": connection_id},
            )

        draft = ConnectionDraft.model_validate(connection_payload)
        if not draft.base_url:
            raise CliError(
                "invalid_config",
                f"Connection {connection_id!r} must set base_url.",
                exit_code=EXIT_USAGE,
                details={"connection_id": connection_id},
            )

        kwargs = {"provider": draft.provider.value}
        if draft.custom_parameters_json:
            try:
                custom_parameters = json.loads(draft.custom_parameters_json)
            except json.JSONDecodeError as exc:
                raise CliError(
                    "invalid_config",
                    f"Connection {connection_id!r} custom_parameters_json must be valid JSON.",
                    exit_code=EXIT_USAGE,
                    details={"connection_id": connection_id},
                ) from exc
            if not isinstance(custom_parameters, dict):
                raise CliError(
                    "invalid_config",
                    f"Connection {connection_id!r} custom_parameters_json must be a JSON object.",
                    exit_code=EXIT_USAGE,
                    details={"connection_id": connection_id},
                )
            kwargs.update({str(key): value for key, value in custom_parameters.items()})

        profiles[connection_id] = EndpointProfile(
            name=connection_id,
            api_key=draft.api_key,
            api_key_env=api_key_env,
            base_url=draft.base_url,
            model=draft.default_model,
            temperature=draft.temperature,
            timeout=draft.timeout,
            max_retries=draft.max_retries,
            concurrency=draft.concurrency,
            kwargs=kwargs,
        )
    return profiles


def _validate_route_connections(profile: WorkflowProfileDetail, connections: dict[str, EndpointProfile]) -> None:
    for route in profile.routes:
        if route.connection_id is None:
            continue
        connection = connections.get(route.connection_id)
        if connection is None:
            raise CliError(
                "invalid_config",
                f"Route {route.step_id.value!r} references unknown connection {route.connection_id!r}.",
                exit_code=EXIT_USAGE,
                details={"step_id": route.step_id.value, "connection_id": route.connection_id},
            )
        if not route.model and not connection.model:
            raise CliError(
                "invalid_config",
                f"Route {route.step_id.value!r} must set model or use a connection with default_model.",
                exit_code=EXIT_USAGE,
                details={"step_id": route.step_id.value, "connection_id": route.connection_id},
            )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
