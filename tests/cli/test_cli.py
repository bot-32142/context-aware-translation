from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from context_aware_translation.application.contracts.common import AcceptedCommand, UserMessage, UserMessageSeverity
from context_aware_translation.application.services.document import DefaultDocumentService
from context_aware_translation.cli.config_file import default_config_path
from context_aware_translation.cli.main import run


def _config_text(env_name: str = "CAT_TEST_API_KEY", *, unknown_connection: bool = False) -> str:
    translator_connection = "missing" if unknown_connection else "test"
    return f"""
version: 1
default_workflow_profile: balanced
connections:
  test:
    display_name: Test
    provider: openai
    api_key_env: {env_name}
    base_url: https://api.example.com/v1
    default_model: test-model
workflow_profiles:
  balanced:
    profile_id: balanced
    name: Balanced
    kind: shared
    target_language: English
    routes:
      - step_id: extractor
        step_label: Extractor
        connection_id: test
        step_config: {{}}
      - step_id: summarizer
        step_label: Summarizer
        connection_id: test
        step_config: {{}}
      - step_id: glossary_translator
        step_label: Glossary translator
        connection_id: test
        step_config: {{}}
      - step_id: translator
        step_label: Translator
        connection_id: {translator_connection}
        step_config: {{}}
      - step_id: polish
        step_label: Polish
        connection_id: test
        step_config: {{}}
      - step_id: reviewer
        step_label: Reviewer
        connection_id: test
        step_config: {{}}
"""


def _write_config(tmp_path: Path, text: str | None = None) -> Path:
    config_path = tmp_path / "cat.yaml"
    config_path.write_text(text or _config_text(), encoding="utf-8")
    return config_path


def _json_stdout(capsys: Any) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out)


def _fake_run_translate_and_export(self: DefaultDocumentService, request: Any) -> AcceptedCommand:
    record = self._runtime.task_store.create(  # noqa: SLF001
        book_id=request.project_id,
        task_type="translate_and_export",
        status="completed",
        document_ids_json=json.dumps([request.document_id]),
        payload_json=json.dumps({"output_path": request.output_path, "format_id": request.format_id}),
    )
    return AcceptedCommand(
        command_name="translate_and_export",
        command_id=record.task_id,
        queue_item_id=record.task_id,
        message=UserMessage(severity=UserMessageSeverity.INFO, text="queued"),
    )


def test_config_path_reports_explicit_path(tmp_path: Path, capsys: Any) -> None:
    config_path = tmp_path / "cat.yaml"

    exit_code = run(["--config", str(config_path), "--json", "config", "path"])

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["data"]["path"] == str(config_path.resolve())
    assert payload["data"]["exists"] is False


def test_config_path_uses_default_when_no_overrides(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAT_CONFIG", raising=False)

    exit_code = run(["--json", "config", "path"])

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["data"]["path"] == str(default_config_path())


def test_config_path_prefers_env_over_local_config(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    local_config = _write_config(tmp_path)
    env_config = tmp_path / "env.yaml"
    env_config.write_text(_config_text(), encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    monkeypatch.setenv("CAT_CONFIG", str(env_config))

    exit_code = run(["--json", "config", "path"])

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["data"]["path"] == str(env_config.resolve())
    assert payload["data"]["path"] != str(local_config.resolve())


def test_config_init_writes_and_refuses_overwrite(tmp_path: Path, capsys: Any) -> None:
    config_path = tmp_path / "cat.yaml"

    assert run(["--config", str(config_path), "--json", "config", "init"]) == 0
    assert config_path.exists()
    assert _json_stdout(capsys)["data"]["created"] is True

    assert run(["--config", str(config_path), "--json", "config", "init"]) == 2
    payload = _json_stdout(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_exists"


def test_config_validate_accepts_valid_config(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("CAT_TEST_API_KEY", "test-key")
    config_path = _write_config(tmp_path)

    exit_code = run(["--config", str(config_path), "--json", "config", "validate"])

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["data"] == {"path": str(config_path.resolve()), "profile": "balanced", "valid": True}


def test_documented_example_config_validates(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    config_path = Path("docs/examples/cat-cli.yaml")

    exit_code = run(["--config", str(config_path), "--json", "config", "validate"])

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["data"]["profile"] == "balanced_deepseek"


def test_config_validate_rejects_missing_env(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.delenv("CAT_TEST_API_KEY", raising=False)
    config_path = _write_config(tmp_path)

    exit_code = run(["--config", str(config_path), "--json", "config", "validate"])

    assert exit_code == 2
    payload = _json_stdout(capsys)
    assert payload["error"]["code"] == "missing_api_key_env"


def test_config_validate_rejects_unknown_route_connection(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("CAT_TEST_API_KEY", "test-key")
    config_path = _write_config(tmp_path, _config_text(unknown_connection=True))

    exit_code = run(["--config", str(config_path), "--json", "config", "validate"])

    assert exit_code == 2
    payload = _json_stdout(capsys)
    assert payload["error"]["code"] == "invalid_config"
    assert "unknown connection" in payload["error"]["message"]


def test_books_list_show_delete_json(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("CAT_TEST_API_KEY", "test-key")
    monkeypatch.setattr(DefaultDocumentService, "run_translate_and_export", _fake_run_translate_and_export)
    config_path = _write_config(tmp_path)

    assert (
        run(
            [
                "--library-root",
                str(tmp_path / "library"),
                "--config",
                str(config_path),
                "--json",
                "run",
                _text_input(tmp_path),
                "--output",
                str(tmp_path / "out.txt"),
            ]
        )
        == 0
    )
    run_payload = _json_stdout(capsys)
    book_id = run_payload.get("data", {}).get("book_id") or run_payload.get("error", {}).get("details", {}).get(
        "book_id"
    )
    assert isinstance(book_id, str)

    assert run(["--library-root", str(tmp_path / "library"), "--json", "books", "list"]) == 0
    list_payload = _json_stdout(capsys)
    assert any(item["project"]["project_id"] == book_id for item in list_payload["data"]["items"])

    assert run(["--library-root", str(tmp_path / "library"), "--json", "books", "show", book_id]) == 0
    show_payload = _json_stdout(capsys)
    assert show_payload["data"]["project"]["project"]["project_id"] == book_id

    assert run(["--library-root", str(tmp_path / "library"), "--json", "books", "delete", book_id, "--yes"]) == 0
    delete_payload = _json_stdout(capsys)
    assert delete_payload["data"]["deleted"] is True


def test_run_creates_book_imports_document_and_waits(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setenv("CAT_TEST_API_KEY", "test-key")
    config_path = _write_config(tmp_path)
    input_path = Path(_text_input(tmp_path))
    output_path = tmp_path / "translated.txt"
    monkeypatch.setattr(DefaultDocumentService, "run_translate_and_export", _fake_run_translate_and_export)

    exit_code = run(
        [
            "--library-root",
            str(tmp_path / "library"),
            "--config",
            str(config_path),
            "--json",
            "run",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = _json_stdout(capsys)
    assert payload["ok"] is True
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["document_id"] == 1
    assert payload["data"]["output_path"] == str(output_path.resolve())


def test_run_with_book_id_reuses_existing_book(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setenv("CAT_TEST_API_KEY", "test-key")
    config_path = _write_config(tmp_path)
    library_root = tmp_path / "library"
    monkeypatch.setattr(DefaultDocumentService, "run_translate_and_export", _fake_run_translate_and_export)

    assert (
        run(
            [
                "--library-root",
                str(library_root),
                "--config",
                str(config_path),
                "--json",
                "run",
                _text_input(tmp_path, "first.txt"),
                "--output",
                str(tmp_path / "first.out.txt"),
            ]
        )
        == 0
    )
    first_payload = _json_stdout(capsys)
    book_id = first_payload["data"]["book_id"]

    assert (
        run(
            [
                "--library-root",
                str(library_root),
                "--json",
                "run",
                _text_input(tmp_path, "second.txt", "goodbye world\n"),
                "--book-id",
                book_id,
                "--output",
                str(tmp_path / "second.out.txt"),
            ]
        )
        == 0
    )
    second_payload = _json_stdout(capsys)
    assert second_payload["data"]["book_id"] == book_id
    assert second_payload["data"]["document_id"] == 2


def test_run_rejects_config_with_book_id(tmp_path: Path, capsys: Any) -> None:
    config_path = tmp_path / "cat.yaml"

    exit_code = run(
        [
            "--config",
            str(config_path),
            "--json",
            "run",
            str(tmp_path / "input.txt"),
            "--book-id",
            "book-1",
            "--output",
            str(tmp_path / "out.txt"),
        ]
    )

    assert exit_code == 2
    payload = _json_stdout(capsys)
    assert payload["error"]["code"] == "usage"


def _text_input(tmp_path: Path, name: str = "input.txt", content: str = "hello world\n") -> str:
    input_path = tmp_path / name
    input_path.write_text(content, encoding="utf-8")
    return str(input_path)
