from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from alembic.config import Config
from alembic.script import ScriptDirectory

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = WORKSPACE_ROOT / "apps" / "api"
ALEMBIC_CONFIG_PATH = API_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = API_ROOT / "alembic"
WEB_DESIGN_DOC = WORKSPACE_ROOT / "docs" / "web应用技术设计方案.md"
DATA_DICTIONARY_DOC = WORKSPACE_ROOT / "docs" / "数据字典.md"


@dataclass(frozen=True)
class DocContractReport:
    ok: bool
    alembic_head: str
    model_tables: list[str]
    design_core_tables: list[str]
    missing_design_tables: list[str]
    extra_design_tables: list[str]
    missing_dictionary_tables: list[str]
    missing_head_documents: list[str]


class DocContractError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check docs against the current Alembic head and ORM table contract."
    )
    parser.add_argument(
        "--json-report-path",
        help="Optional path for a machine-readable report.",
    )
    return parser.parse_args()


def alembic_head() -> str:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise DocContractError(f"Expected exactly one Alembic head, found {len(heads)}: {heads}")
    return heads[0]


def model_tables() -> list[str]:
    sys.path.insert(0, str(API_ROOT))
    session_module = importlib.import_module("app.db.session")
    importlib.import_module("app.db.models")

    base = cast(Any, session_module).Base
    return sorted(cast("dict[str, object]", base.metadata.tables))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def design_core_tables(text: str) -> list[str]:
    match = re.search(r"### 8\.1 核心表(?P<section>.*?)### 8\.2 关键字段", text, re.S)
    if match is None:
        raise DocContractError("Could not find the design doc core table section.")
    return sorted(set(re.findall(r"\| `([^`]+)` \|", match.group("section"))))


def missing_head_documents(head: str, documents: dict[str, str]) -> list[str]:
    return sorted(name for name, text in documents.items() if head not in text)


def build_report() -> DocContractReport:
    head = alembic_head()
    tables = model_tables()
    web_design = read_text(WEB_DESIGN_DOC)
    data_dictionary = read_text(DATA_DICTIONARY_DOC)
    core_tables = design_core_tables(web_design)
    table_set = set(tables)
    core_table_set = set(core_tables)
    missing_design_tables = sorted(table_set - core_table_set)
    extra_design_tables = sorted(core_table_set - table_set)
    missing_dictionary_tables = sorted(table for table in tables if f"`{table}`" not in data_dictionary)
    missing_head_docs = missing_head_documents(
        head,
        {
            str(WEB_DESIGN_DOC.relative_to(WORKSPACE_ROOT)): web_design,
            str(DATA_DICTIONARY_DOC.relative_to(WORKSPACE_ROOT)): data_dictionary,
        },
    )
    ok = not (
        missing_design_tables
        or extra_design_tables
        or missing_dictionary_tables
        or missing_head_docs
    )
    return DocContractReport(
        ok=ok,
        alembic_head=head,
        model_tables=tables,
        design_core_tables=core_tables,
        missing_design_tables=missing_design_tables,
        extra_design_tables=extra_design_tables,
        missing_dictionary_tables=missing_dictionary_tables,
        missing_head_documents=missing_head_docs,
    )


def write_report(path_value: str, report: DocContractReport) -> None:
    path = Path(path_value)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = build_report()
    if args.json_report_path:
        write_report(args.json_report_path, report)
    if report.ok:
        print(
            "Documentation contract check passed: "
            f"head={report.alembic_head}, tables={len(report.model_tables)}"
        )
        return 0
    print("Documentation contract check failed.", file=sys.stderr)
    for field_name in (
        "missing_head_documents",
        "missing_design_tables",
        "extra_design_tables",
        "missing_dictionary_tables",
    ):
        values = getattr(report, field_name)
        if values:
            print(f"{field_name}: {values}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
