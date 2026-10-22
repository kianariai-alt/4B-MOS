"""Validate and render the inactive knee design review without application I/O.

This is a document tool, not an interview or clinical-rule evaluator. It imports
no application, database, registry, network, or model dependencies.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = "4b.knee-review-draft.v1"
DEFAULT_DRAFT = (
    Path(__file__).resolve().parents[2]
    / "docs" / "orthopedic-intelligence" / "knee-review-draft.json"
)
MAX_DRAFT_BYTES = 2 * 1024 * 1024
REQUIRED_CONSTRAINTS = {
    "unknown_is_not_no", "zero_is_not_missing", "patient_report_unconfirmed",
    "parallel_paths", "meniscus_scope", "targeted_mri", "no_single_score",
    "biologics_distinct", "animal_exosomes", "combination_synergy",
    "clinic_policy_separate", "renal_medication_review", "incomplete_scope",
    "physician_authority", "no_diagnostic_probabilities",
}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    node_count: int = 0
    stage_count: int = 0
    runtime_enabled: bool = False
    clinically_validated: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, **asdict(self)}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _keys(item: dict, expected: set[str], label: str, errors: list[str]) -> None:
    if set(item) != expected:
        errors.append(f"{label}: fields do not match the v1 review contract")


def _https(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme == "https" and bool(parts.hostname)
            and parts.username is None and parts.password is None
        )
    except ValueError:
        return False


def _iso_date(value: Any) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_draft(draft: Any) -> ValidationReport:
    """Fail closed if a review placeholder appears executable or approved.

    The 26 concepts are reconstructed from the handoff outline. Their number
    does not establish equivalence with the missing original 26-node artifact.
    """
    report = ValidationReport()
    errors = report.errors
    if not isinstance(draft, dict):
        errors.append("draft must be a JSON object")
        return report
    _keys(draft, {
        "schema_version", "content_version", "title_fa", "status",
        "runtime_enabled", "registry_imported", "clinically_validated",
        "original_artifact", "scope", "provenance", "unresolved_inputs_fa",
        "stages", "nodes", "parallel_candidate_node_ids", "constraints",
        "references",
    }, "draft", errors)
    if draft.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if not _text(draft.get("content_version")) or not _text(draft.get("title_fa")):
        errors.append("content_version and title_fa are required")
    if draft.get("status") != "draft_design_review":
        errors.append("status must be draft_design_review")
    for key in ("runtime_enabled", "registry_imported", "clinically_validated"):
        if draft.get(key) is not False:
            errors.append(f"{key} must be explicitly false")

    original = draft.get("original_artifact")
    if not isinstance(original, dict):
        errors.append("original_artifact is required")
    else:
        _keys(original, {
            "name", "availability", "verified_sha256", "reconstruction_basis",
            "mapping_to_original",
        }, "original_artifact", errors)
        if (
            original.get("name") != "4B-Knee-Decision-Design-v1.zip"
            or original.get("availability") != "not_available"
            or original.get("verified_sha256") is not None
            or original.get("reconstruction_basis") != "user_handoff_outline"
            or original.get("mapping_to_original") != "unknown"
        ):
            errors.append("original artifact recovery or node equivalence cannot be claimed")

    scope = draft.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope is required")
    else:
        _keys(scope, {"entry_fa", "minimum_age_years", "incomplete_paths_fa"}, "scope", errors)
        if not _text(scope.get("entry_fa")) or scope.get("minimum_age_years") is not None:
            errors.append("scope must retain the unresolved age threshold")
        incomplete = scope.get("incomplete_paths_fa")
        if not isinstance(incomplete, list) or len(incomplete) < 5 or not all(map(_text, incomplete)):
            errors.append("incomplete scope must remain explicit")
    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance is required")
    else:
        _keys(provenance, {"origin", "recorded_on", "detail_fa"}, "provenance", errors)
        if (
            provenance.get("origin") != "user_handoff_unverified"
            or not _iso_date(provenance.get("recorded_on"))
            or not _text(provenance.get("detail_fa"))
        ):
            errors.append("handoff provenance is invalid")
    unresolved = draft.get("unresolved_inputs_fa")
    if not isinstance(unresolved, list) or len(unresolved) < 3 or not all(map(_text, unresolved)):
        errors.append("unresolved physician text, clinical review and source review must remain explicit")

    references = draft.get("references")
    reference_ids: set[str] = set()
    if not isinstance(references, list) or not references:
        errors.append("references must be a nonempty list")
        references = []
    for index, reference in enumerate(references):
        label = f"reference[{index}]"
        if not isinstance(reference, dict):
            errors.append(f"{label}: must be an object")
            continue
        _keys(reference, {
            "id", "title", "url", "verification_status", "section", "page",
            "source_version", "rights_status",
        }, label, errors)
        reference_id = reference.get("id")
        if not _text(reference_id) or reference_id in reference_ids:
            errors.append(f"{label}: missing or duplicate id")
        else:
            reference_ids.add(reference_id)
        if not _text(reference.get("title")) or not _https(reference.get("url")):
            errors.append(f"{label}: title and HTTPS candidate source URL required")
        if (
            reference.get("verification_status") != "candidate_not_verified_in_this_review"
            or reference.get("rights_status") != "not_cleared_for_product_retrieval"
            or any(reference.get(key) is not None for key in ("section", "page", "source_version"))
        ):
            errors.append(f"{label}: unverified locator, source version or rights cannot be asserted")

    nodes = draft.get("nodes")
    node_ids: set[str] = set()
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        nodes = []
    report.node_count = len(nodes)
    if len(nodes) != 26:
        errors.append("this review revision requires 26 conceptual placeholders")
    for index, node in enumerate(nodes):
        label = f"node[{index}]"
        if not isinstance(node, dict):
            errors.append(f"{label}: must be an object")
            continue
        _keys(node, {
            "id", "version", "title_fa", "review_purpose_fa", "status",
            "runtime_enabled", "clinical_question", "answer_schema",
            "display_condition", "medical_rule", "provenance",
            "candidate_reference_ids",
        }, label, errors)
        node_id = node.get("id")
        if (
            not isinstance(node_id, str)
            or not re.fullmatch(r"KNEE-R\d{2}", node_id)
            or node_id in node_ids
        ):
            errors.append(f"{label}: invalid or duplicate id")
        else:
            node_ids.add(node_id)
        if not all(_text(node.get(key)) for key in ("version", "title_fa", "review_purpose_fa")):
            errors.append(f"{label}: version, title and review purpose required")
        if node.get("status") != "draft" or node.get("runtime_enabled") is not False:
            errors.append(f"{label}: every node must remain draft and inactive")
        if any(node.get(key) is not None for key in (
            "clinical_question", "answer_schema", "display_condition", "medical_rule",
        )):
            errors.append(f"{label}: clinical wording, answer schema, condition and rule are unresolved")
        if node.get("provenance") != "user_handoff_outline_reconstruction":
            errors.append(f"{label}: reconstruction provenance required")
        candidates = node.get("candidate_reference_ids")
        if (
            not isinstance(candidates, list)
            or any(not isinstance(value, str) or value not in reference_ids for value in candidates)
            or (isinstance(candidates, list) and len(set(candidates)) != len(candidates))
        ):
            errors.append(f"{label}: unknown or duplicate candidate reference")
    if node_ids != {f"KNEE-R{number:02d}" for number in range(1, 27)}:
        errors.append("conceptual node identifiers must be KNEE-R01 through KNEE-R26")

    stages = draft.get("stages")
    stage_ids: set[str] = set()
    assigned_nodes: list[str] = []
    if not isinstance(stages, list):
        errors.append("stages must be a list")
        stages = []
    report.stage_count = len(stages)
    if len(stages) != 9:
        errors.append("this review revision requires nine design stages")
    for index, stage in enumerate(stages):
        label = f"stage[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{label}: must be an object")
            continue
        _keys(stage, {"id", "title_fa", "node_ids"}, label, errors)
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or stage_id in stage_ids:
            errors.append(f"{label}: missing or duplicate id")
        else:
            stage_ids.add(stage_id)
        if not _text(stage.get("title_fa")):
            errors.append(f"{label}: title required")
        members = stage.get("node_ids")
        if (
            not isinstance(members, list) or not members
            or any(not isinstance(value, str) or value not in node_ids for value in members)
        ):
            errors.append(f"{label}: unknown or missing conceptual nodes")
        else:
            assigned_nodes.extend(members)
    if len(assigned_nodes) != len(set(assigned_nodes)) or set(assigned_nodes) != node_ids:
        errors.append("each conceptual node must appear in exactly one design stage")
    if draft.get("parallel_candidate_node_ids") != ["KNEE-R09", "KNEE-R10", "KNEE-R11"]:
        errors.append("parallel candidate concepts must remain explicit and nonexclusive")

    constraints = draft.get("constraints")
    constraint_ids: set[str] = set()
    if not isinstance(constraints, list):
        errors.append("constraints must be a list")
        constraints = []
    for index, constraint in enumerate(constraints):
        label = f"constraint[{index}]"
        if not isinstance(constraint, dict):
            errors.append(f"{label}: must be an object")
            continue
        _keys(constraint, {"id", "text_fa", "basis", "status", "runtime_enabled"}, label, errors)
        constraint_id = constraint.get("id")
        if not isinstance(constraint_id, str) or constraint_id in constraint_ids:
            errors.append(f"{label}: missing or duplicate id")
        else:
            constraint_ids.add(constraint_id)
        if (
            not _text(constraint.get("text_fa"))
            or constraint.get("basis") != "user_handoff_requires_independent_review"
            or constraint.get("status") != "draft"
            or constraint.get("runtime_enabled") is not False
        ):
            errors.append(f"{label}: handoff constraint must remain draft and inactive")
    if constraint_ids != REQUIRED_CONSTRAINTS:
        errors.append("all declared knowledge and workflow limits must remain present")
    return report


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_draft(path: Path) -> Any:
    with path.open("rb") as stream:
        raw = stream.read(MAX_DRAFT_BYTES + 1)
    if len(raw) > MAX_DRAFT_BYTES:
        raise ValueError("draft exceeds 2 MiB")
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite JSON value")),
    )


def render_html(draft: dict) -> str:
    """Produce a self-contained Persian review, escaping every data value."""
    report = validate_draft(draft)
    if not report.ok:
        raise ValueError("invalid or potentially active draft cannot be rendered")
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)
    nodes = {node["id"]: node for node in draft["nodes"]}
    sections = []
    for stage in draft["stages"]:
        rows = []
        for node_id in stage["node_ids"]:
            node = nodes[node_id]
            rows.append(
                f'<article><p class="id">{esc(node_id)} · {esc(node["version"])}</p>'
                f'<h3>{esc(node["title_fa"])}</h3><p>{esc(node["review_purpose_fa"])}</p>'
                '<p class="pending">پیش‌نویس غیرفعال؛ متن سؤال، نوع پاسخ، شرط نمایش '
                'و قاعده: تعیین‌نشده و منتظر ورودی پزشک.</p></article>'
            )
        sections.append(f'<section><h2>{esc(stage["title_fa"])}</h2>{"".join(rows)}</section>')
    limits = "".join(f'<li>{esc(item["text_fa"])}</li>' for item in draft["constraints"])
    pending = "".join(f"<li>{esc(item)}</li>" for item in draft["unresolved_inputs_fa"])
    references = "".join(
        f'<li><a href="{esc(item["url"])}" rel="noreferrer noopener">{esc(item["title"])}</a>'
        ' — فقط منبع پیشنهادی؛ صفحه، بخش، نسخه و مجوز استفاده در محصول تأیید نشده است.</li>'
        for item in draft["references"]
    )
    return f'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{esc(draft["title_fa"])}</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;line-height:1.9;max-width:1050px;margin:2rem auto;padding:0 1rem;color:#172c3a;background:#f5f7fa}}h1,h2{{color:#143a52}}section,.notice{{background:white;border:1px solid #cad5df;border-radius:10px;padding:1rem 1.4rem;margin:1rem 0}}article{{border-top:1px solid #dce3e9;padding:.5rem 0}}.id{{direction:ltr;text-align:right;font-family:monospace;color:#526371}}.pending{{color:#775000}}.notice{{border-right:6px solid #b97800}}a{{overflow-wrap:anywhere}}@media print{{body{{background:white}}section{{break-inside:auto}}article{{break-inside:avoid}}}}</style></head><body>
<h1>{esc(draft["title_fa"])}</h1>
<p>نسخه محتوا: <bdi>{esc(draft["content_version"])}</bdi> · ۹ مرحله · ۲۶ جایگاه مفهومی</p>
<div class="notice"><strong>فقط برای بازبینی طراحی؛ تمام محتوا پیش‌نویس و غیرفعال است.</strong>
<p>بسته اصلی ۲۶گرهی در این محیط موجود نیست. این سند از خلاصه تحویل بازسازی شده و بازیابی یا تطبیق گره‌به‌گره اصل نیست. ترتیب مرحله‌ها مسیر اجرایی مصاحبه نیست؛ پیکان، آستانه بالینی یا تشخیص تولید نمی‌کند.</p>
<p>این فایل آفلاین است؛ به پایگاه داده، Registry یا مسیر بیمار متصل نمی‌شود. معتبر بودن ساختار فایل به معنی تأیید علمی، مجوز استفاده از منبع یا آمادگی استفاده بالینی نیست.</p></div>
<section><h2>ورودی‌های لازم برای ادامه</h2><ul>{pending}</ul></section>
<section><h2>مرز کاربرد</h2><p>{esc(draft["scope"]["entry_fa"])}</p><p>آستانه سنی و معیارهای اجرایی تعیین نشده‌اند. مسیرهای ناقص: {esc('، '.join(draft["scope"]["incomplete_paths_fa"]))}.</p>
<p>سه جایگاه KNEE-R09، KNEE-R10 و KNEE-R11 می‌توانند هم‌زمان برای بررسی مطرح باشند؛ هیچ‌کدام انتخاب اجباری یک تشخیص نیست.</p></section>
{"".join(sections)}
<section><h2>محدودیت‌های دانشی و مسئولیت بازبینی</h2><p>موارد زیر از تحویل کاربر آمده‌اند و در این سند به قواعد تأییدشده تبدیل نشده‌اند.</p><ul>{limits}</ul></section>
<section><h2>منابع پیشنهادی برای بررسی مستقل</h2><p>لینک‌ها فقط با انتخاب خواننده باز می‌شوند؛ نمایش آفلاین هیچ دریافت شبکه‌ای ندارد. وجود لینک، ارجاع دقیق گزاره یا مجوز نمایه‌سازی تجاری نیست.</p><ul>{references}</ul></section>
</body></html>'''


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="بررسی و نمایش آفلاین طرح غیرفعال زانو")
    parser.add_argument("--input", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--html", type=Path, help="مسیر خروجی HTML مستقل برای بازبینی")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        draft = load_draft(args.input)
    except (OSError, UnicodeError, ValueError):
        report = ValidationReport(errors=["draft_unreadable_or_invalid_json"])
    else:
        report = validate_draft(draft)
        if report.ok and args.html is not None:
            try:
                if args.html.suffix.casefold() != ".html" or args.html.resolve() == args.input.resolve():
                    raise ValueError("HTML output must be a separate .html file")
                args.html.parent.mkdir(parents=True, exist_ok=True)
                args.html.write_text(render_html(draft), encoding="utf-8")
            except (OSError, ValueError):
                report.errors.append("html_output_unavailable")
    if args.format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("ساختار طرح معتبر است؛ محتوا غیرفعال و منتظر بازبینی پزشک است." if report.ok else "بررسی طرح ناموفق بود.")
        for error in report.errors:
            print(f"ERROR: {error}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
