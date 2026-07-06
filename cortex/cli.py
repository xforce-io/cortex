from __future__ import annotations

import argparse
import json
import sys

from .app import CortexApp


def print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=None, sort_keys=True))


def parse_params(values: list[str]) -> dict:
    params = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"--param must be key=value: {item}")
        key, value = item.split("=", 1)
        if value.isdigit():
            params[key] = int(value)
        else:
            try:
                params[key] = float(value)
            except ValueError:
                params[key] = value
    return params


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortex")
    sub = parser.add_subparsers(dest="group", required=True)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="command", required=True)
    project_sub.add_parser("list")
    project_create = project_sub.add_parser("create")
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--owner", required=True)
    project_create.add_argument("--team", required=True)
    project_create.add_argument("--description", default="")
    project_datasets = project_sub.add_parser("datasets")
    project_datasets.add_argument("project_id")
    project_link = project_sub.add_parser("link-dataset")
    project_link.add_argument("project_id")
    project_link.add_argument("dataset_id")
    project_link.add_argument("--role", default="train")
    project_link.add_argument("--version-policy", default="latest")
    project_link.add_argument("--pinned-version")
    project_link.add_argument("--added-by", default="unknown")

    dataset = sub.add_parser("dataset")
    ds_sub = dataset.add_subparsers(dest="command", required=True)
    ds_create = ds_sub.add_parser("create")
    ds_create.add_argument("--name", required=True)
    ds_create.add_argument("--type", required=True)
    ds_create.add_argument("--owner", required=True)
    ds_create.add_argument("--team", required=True)
    ds_create.add_argument("--description", default="")
    ds_create.add_argument("--visibility", default="team")
    ds_create.add_argument("--project")
    ds_create.add_argument("--tag", action="append", default=[])
    ds_create.add_argument("--domain", default="")
    ds_create.add_argument("--source-system", default="")

    ds_sub.add_parser("show").add_argument("dataset_id")
    ds_lineage = ds_sub.add_parser("lineage")
    ds_lineage.add_argument("dataset_ref")

    version = ds_sub.add_parser("version")
    version_sub = version.add_subparsers(dest="version_command", required=True)
    version_add = version_sub.add_parser("add")
    version_add.add_argument("dataset_id")
    version_add.add_argument("--version", required=True)
    version_add.add_argument("--storage-uri", required=True)
    version_add.add_argument("--format", required=True)
    version_add.add_argument("--checksum")
    version_add.add_argument("--created-by", default="unknown")

    train = sub.add_parser("train")
    train_sub = train.add_subparsers(dest="command", required=True)
    train_sub.add_parser("templates")
    submit = train_sub.add_parser("submit")
    submit.add_argument("--template", required=True)
    submit.add_argument("--dataset", required=True)
    submit.add_argument("--experiment", required=True)
    submit.add_argument("--owner", required=True)
    submit.add_argument("--team", required=True)
    submit.add_argument("--project")
    submit.add_argument("--param", action="append", default=[])
    submit.add_argument("--wait", action="store_true")
    train_sub.add_parser("status").add_argument("job_id")
    train_sub.add_parser("logs").add_argument("job_id")
    train_sub.add_parser("cancel").add_argument("job_id")
    train_sub.add_parser("retry").add_argument("job_id")

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="command", required=True)
    run_sub.add_parser("show").add_argument("run_id")
    run_sub.add_parser("artifacts").add_argument("run_id")

    model = sub.add_parser("model")
    model_sub = model.add_subparsers(dest="command", required=True)
    register = model_sub.add_parser("register")
    register.add_argument("name")
    register.add_argument("--run-id", required=True)
    register.add_argument("--artifact-path", required=True)
    register.add_argument("--description", default="")

    alias = model_sub.add_parser("alias")
    alias_sub = alias.add_subparsers(dest="alias_command", required=True)
    alias_set = alias_sub.add_parser("set")
    alias_set.add_argument("name")
    alias_set.add_argument("alias")
    alias_set.add_argument("--version", required=True)
    alias_set.add_argument("--operator", default="unknown")
    alias_set.add_argument("--reason", default="")
    alias_delete = alias_sub.add_parser("delete")
    alias_delete.add_argument("name")
    alias_delete.add_argument("alias")
    alias_delete.add_argument("--operator", default="unknown")
    alias_delete.add_argument("--reason", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = CortexApp.open()
    try:
        if args.group == "project" and args.command == "list":
            print_json(app.list_projects())
        elif args.group == "project" and args.command == "create":
            print_json(app.create_project(args.name, args.owner, args.team, args.description))
        elif args.group == "project" and args.command == "datasets":
            print_json(app.list_project_datasets(args.project_id))
        elif args.group == "project" and args.command == "link-dataset":
            print_json(app.link_project_dataset(args.project_id, args.dataset_id, args.role, args.version_policy, args.pinned_version, args.added_by))
        elif args.group == "dataset" and args.command == "create":
            print_json(
                app.create_dataset(
                    args.name,
                    args.type,
                    args.owner,
                    args.team,
                    args.description,
                    tags=args.tag,
                    visibility=args.visibility,
                    project_id=args.project,
                    domain=args.domain,
                    source_system=args.source_system,
                )
            )
        elif args.group == "dataset" and args.command == "show":
            print_json(app.get_dataset(args.dataset_id))
        elif args.group == "dataset" and args.command == "lineage":
            print_json(app.dataset_lineage(args.dataset_ref))
        elif args.group == "dataset" and args.command == "version" and args.version_command == "add":
            print_json(app.add_dataset_version(args.dataset_id, args.version, args.storage_uri, args.format, args.checksum, created_by=args.created_by))
        elif args.group == "train" and args.command == "templates":
            print_json(app.list_templates())
        elif args.group == "train" and args.command == "submit":
            print_json(app.submit_training_job(args.template, args.dataset, args.experiment, parse_params(args.param), args.owner, args.team, wait=args.wait, project_id=args.project))
        elif args.group == "train" and args.command == "status":
            print_json(app.get_training_job(args.job_id))
        elif args.group == "train" and args.command == "logs":
            print(app.get_job_logs(args.job_id), end="")
        elif args.group == "train" and args.command == "cancel":
            print_json(app.cancel_training_job(args.job_id))
        elif args.group == "train" and args.command == "retry":
            print_json(app.retry_training_job(args.job_id, wait=True))
        elif args.group == "run" and args.command == "show":
            print_json(app.get_run(args.run_id))
        elif args.group == "run" and args.command == "artifacts":
            print_json(app.list_run_artifacts(args.run_id))
        elif args.group == "model" and args.command == "register":
            print_json(app.register_model_version(args.name, args.run_id, args.artifact_path, args.description))
        elif args.group == "model" and args.command == "alias" and args.alias_command == "set":
            print_json(app.set_model_alias(args.name, args.alias, args.version, args.operator, args.reason))
        elif args.group == "model" and args.command == "alias" and args.alias_command == "delete":
            print_json(app.delete_model_alias(args.name, args.alias, args.operator, args.reason))
        else:
            raise SystemExit("unsupported command")
        return 0
    except ValueError as exc:
        print_json({"error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
