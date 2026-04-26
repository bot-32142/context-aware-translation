from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

from context_aware_translation.application.contracts.common import ContractModel
from context_aware_translation.application.contracts.document import RunTranslateAndExportRequest
from context_aware_translation.application.contracts.work import ImportDocumentsRequest, InspectImportPathsRequest
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.storage.models.book import BookStatus
from context_aware_translation.workflow.tasks.models import STATUS_COMPLETED

from .config_file import load_cli_config, resolve_config_path, write_starter_config
from .output import (
    EXIT_BLOCKED,
    EXIT_TASK_FAILED,
    EXIT_USAGE,
    CliError,
    error_from_exception,
    print_human_error,
    print_json_envelope,
)
from .runtime import cli_context
from .wait import wait_for_task


def main() -> None:
    raise SystemExit(run())


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = command_name(args)
    try:
        data = dispatch(args)
    except (ApplicationError, CliError) as exc:
        error, exit_code = error_from_exception(exc)
        if bool(getattr(args, "json", False)):
            print_json_envelope(ok=False, command=command, error=error)
        else:
            print_human_error(str(error["message"]))
        return exit_code
    except KeyboardInterrupt:
        error = {"code": "cancelled", "message": "Interrupted.", "details": {}}
        if bool(getattr(args, "json", False)):
            print_json_envelope(ok=False, command=command, error=error)
        else:
            print_human_error("Interrupted.")
        return EXIT_TASK_FAILED
    except Exception as exc:  # noqa: BLE001
        error, exit_code = error_from_exception(exc)
        if bool(getattr(args, "json", False)):
            print_json_envelope(ok=False, command=command, error=error)
        else:
            print_human_error(str(error["message"]))
        return exit_code

    if bool(getattr(args, "json", False)):
        print_json_envelope(ok=True, command=command, data=data)
    elif not bool(getattr(args, "quiet", False)):
        print_human_success(command, data)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--library-root", dest="library_root")
    common.add_argument("--config", dest="config_path")
    common.add_argument("--json", action="store_true")
    common.add_argument("--quiet", action="store_true")
    common.add_argument("--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="cat-cli", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", parents=[common])
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("path", parents=[common])
    init_parser = config_subparsers.add_parser("init", parents=[common])
    init_parser.add_argument("--force", action="store_true")
    config_subparsers.add_parser("validate", parents=[common])

    run_parser = subparsers.add_parser("run", parents=[common])
    run_parser.add_argument("input")
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--book-id")
    run_parser.add_argument("--book-name")
    run_parser.add_argument("--type", dest="document_type")
    run_parser.add_argument("--format", dest="format_id")

    books_parser = subparsers.add_parser("books", parents=[common])
    books_subparsers = books_parser.add_subparsers(dest="books_command", required=True)
    books_subparsers.add_parser("list", parents=[common])
    show_parser = books_subparsers.add_parser("show", parents=[common])
    show_parser.add_argument("book_id")
    delete_parser = books_subparsers.add_parser("delete", parents=[common])
    delete_parser.add_argument("book_id")
    delete_parser.add_argument("--yes", action="store_true")
    delete_parser.add_argument("--permanent", action="store_true")
    return parser


def command_name(args: argparse.Namespace) -> str:
    command = str(getattr(args, "command", ""))
    if command == "config":
        return f"config.{getattr(args, 'config_command', '')}"
    if command == "books":
        return f"books.{getattr(args, 'books_command', '')}"
    return command


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = str(args.command)
    if command == "config":
        return dispatch_config(args)
    if command == "books":
        return dispatch_books(args)
    if command == "run":
        return run_one_shot(args)
    raise CliError("usage", f"Unsupported command: {command}", exit_code=EXIT_USAGE)


def dispatch_config(args: argparse.Namespace) -> dict[str, Any]:
    config_command = str(args.config_command)
    path = resolve_config_path(getattr(args, "config_path", None), require_exists=config_command == "validate")
    if config_command == "path":
        return {"path": str(path), "exists": path.exists()}
    if config_command == "init":
        write_starter_config(path, force=bool(getattr(args, "force", False)))
        return {"path": str(path), "created": True}
    if config_command == "validate":
        resolved = load_cli_config(path)
        return {"path": str(path), "profile": resolved.profile_key, "valid": True}
    raise CliError("usage", f"Unsupported config command: {config_command}", exit_code=EXIT_USAGE)


def dispatch_books(args: argparse.Namespace) -> dict[str, Any]:
    library_root = _optional_path(getattr(args, "library_root", None))
    books_command = str(args.books_command)
    with cli_context(library_root) as context:
        if books_command == "list":
            state = context.services.projects.list_projects()
            return cast(dict[str, Any], _payload(state))
        if books_command == "show":
            project = context.services.projects.get_project(str(args.book_id))
            workboard = context.services.work.get_workboard(str(args.book_id))
            return {"project": _payload(project), "workboard": _payload(workboard)}
        if books_command == "delete":
            if not bool(getattr(args, "yes", False)):
                raise CliError("confirmation_required", "Pass --yes to delete a book.", exit_code=EXIT_USAGE)
            context.services.projects.delete_project(
                str(args.book_id), permanent=bool(getattr(args, "permanent", False))
            )
            return {"book_id": str(args.book_id), "deleted": True, "permanent": bool(getattr(args, "permanent", False))}
    raise CliError("usage", f"Unsupported books command: {books_command}", exit_code=EXIT_USAGE)


def run_one_shot(args: argparse.Namespace) -> dict[str, Any]:
    library_root = _optional_path(getattr(args, "library_root", None))
    input_path = Path(str(args.input)).expanduser().resolve()
    output_path = Path(str(args.output)).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with cli_context(library_root) as context:
        if getattr(args, "book_id", None):
            if getattr(args, "config_path", None):
                raise CliError("usage", "--config cannot be used with --book-id in v1.", exit_code=EXIT_USAGE)
            if getattr(args, "book_name", None):
                raise CliError("usage", "--book-name cannot be used with --book-id.", exit_code=EXIT_USAGE)
            book_id = str(args.book_id)
            context.runtime.get_book(book_id)
        else:
            config_path = resolve_config_path(getattr(args, "config_path", None), require_exists=True)
            resolved = load_cli_config(config_path)
            book_name = _book_name(context, input_path, getattr(args, "book_name", None))
            book = context.runtime.book_manager.create_book(book_name, custom_config=resolved.custom_config)
            book_id = book.book_id
            context.runtime.invalidate_projects()
            context.runtime.invalidate_setup(book_id)
            context.runtime.invalidate_workboard(book_id)

        before_ids = {row.document.document_id for row in context.services.work.get_workboard(book_id).rows}
        document_type = resolve_document_type(context, book_id, [input_path], getattr(args, "document_type", None))
        context.services.work.import_documents(
            ImportDocumentsRequest(project_id=book_id, paths=[str(input_path)], document_type=document_type)
        )
        workboard = context.services.work.get_workboard(book_id)
        imported_rows = [row for row in workboard.rows if row.document.document_id not in before_ids]
        if len(imported_rows) != 1:
            raise CliError(
                "unsupported_import",
                "cat-cli run expects exactly one imported document in v1.",
                exit_code=EXIT_BLOCKED,
                details={"imported_count": len(imported_rows), "book_id": book_id},
            )
        document_id = imported_rows[0].document.document_id
        export_state = context.services.document.prepare_translate_and_export(book_id, document_id)
        format_id = resolve_format_id(export_state.available_formats, output_path, getattr(args, "format_id", None))
        accepted = context.services.document.run_translate_and_export(
            RunTranslateAndExportRequest(
                project_id=book_id,
                document_id=document_id,
                format_id=format_id,
                output_path=str(output_path),
                use_batch=False,
                use_reembedding=False,
                enable_polish=True,
            )
        )
        task_id = accepted.queue_item_id or accepted.command_id
        if task_id is None:
            raise CliError("internal", "Translate and Export did not return a task id.")
        record = wait_for_task(context, task_id)
        data = {
            "book_id": book_id,
            "project_id": book_id,
            "document_id": document_id,
            "task_id": task_id,
            "status": record.status,
            "phase": record.phase,
            "output_path": str(output_path),
        }
        if record.status != STATUS_COMPLETED:
            raise CliError(
                "task_failed",
                "Translate and Export did not complete successfully.",
                exit_code=EXIT_TASK_FAILED,
                details={
                    "book_id": book_id,
                    "document_id": document_id,
                    "task_id": task_id,
                    "status": record.status,
                    "phase": record.phase,
                    "last_error": record.last_error,
                },
            )
        return data


def resolve_document_type(
    context: Any,
    book_id: str,
    paths: list[Path],
    requested_type: str | None,
) -> str:
    if requested_type:
        return requested_type
    inspection = context.services.work.inspect_import_paths(
        InspectImportPathsRequest(project_id=book_id, paths=[str(path) for path in paths])
    )
    if inspection.error_message:
        raise CliError("invalid_import", inspection.error_message, exit_code=EXIT_USAGE)
    if len(inspection.available_types) != 1:
        choices = [option.document_type for option in inspection.available_types]
        raise CliError(
            "ambiguous_import_type",
            "Pass --type to choose an import type.",
            exit_code=EXIT_USAGE,
            details={"choices": ", ".join(choices)},
        )
    return str(inspection.available_types[0].document_type)


def resolve_format_id(available_formats: list[Any], output_path: Path, requested_format: str | None) -> str:
    available_by_id = {str(option.format_id): option for option in available_formats}
    if requested_format:
        if requested_format not in available_by_id:
            raise CliError(
                "unsupported_format",
                f"Unsupported export format: {requested_format}",
                exit_code=EXIT_USAGE,
                details={"choices": ", ".join(sorted(available_by_id))},
            )
        return requested_format

    suffix = output_path.suffix.lower().removeprefix(".")
    if suffix:
        if suffix in available_by_id:
            return suffix
        raise CliError(
            "unsupported_format",
            f"Cannot infer export format from output suffix: .{suffix}",
            exit_code=EXIT_USAGE,
            details={"choices": ", ".join(sorted(available_by_id))},
        )
    default = next(
        (option for option in available_formats if option.is_default),
        available_formats[0] if available_formats else None,
    )
    if default is None:
        raise CliError("unsupported_format", "No export formats are available.", exit_code=EXIT_USAGE)
    return str(default.format_id)


def print_human_success(command: str, data: dict[str, Any]) -> None:
    if command == "config.path":
        print(data["path"])
        return
    if command == "config.init":
        print(f"Created config: {data['path']}")
        return
    if command == "config.validate":
        print(f"Config is valid: {data['path']}")
        return
    if command == "books.list":
        for item in data.get("items", []):
            project = item.get("project", {})
            print(f"{project.get('project_id')}\t{project.get('name')}")
        return
    if command == "books.show":
        project = data["project"]["project"]
        print(f"Book: {project['name']} ({project['project_id']})")
        for row in data["workboard"].get("rows", []):
            doc = row["document"]
            print(f"{doc['document_id']}\t{doc['label']}\t{row['state_summary']}")
        return
    if command == "books.delete":
        print(f"Deleted book: {data['book_id']}")
        return
    if command == "run":
        print(f"Book: {data['book_id']}")
        print(f"Document: {data['document_id']}")
        print(f"Task: {data['task_id']}")
        print(f"Done: {data['output_path']}")
        return
    print(data)


def _book_name(context: Any, input_path: Path, requested_name: str | None) -> str:
    if requested_name:
        return requested_name
    base_name = input_path.stem or input_path.name or "Translation"
    existing = {book.name for book in context.runtime.book_manager.list_books(status=BookStatus.ACTIVE)}
    if base_name not in existing:
        return base_name
    index = 2
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in existing:
            return candidate
        index += 1


def _optional_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def _payload(value: Any) -> Any:
    if isinstance(value, ContractModel):
        return value.to_payload()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


if __name__ == "__main__":
    main()
