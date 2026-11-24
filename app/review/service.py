from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.pipeline import run


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f"{RULE_VERSION}:{fingerprint}".encode()).hexdigest()
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
    report = run(data)
    report["manifest"] = dict(
        sha256=fingerprint,
        version=RULE_VERSION,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
    )
    return store.register(run_id, report)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")
    if status == "APPROVED" and not current["report"]["balance"]["releasable"]:
        raise DomainIssue("UNRESOLVED_ISSUES")
    return store.revise(run_id, revision, status, note.strip(), now())


def pin(run, group):
    """固定签发时刻的组证据：来源清单、核对账和业务计算快照。"""
    report = run["report"]
    case = next(item for item in report["cases"] if item["case"] == group["case"])
    return dict(
        schema="group-evidence/1",
        run_id=run["id"],
        case=group["case"],
        manifest=report["manifest"],
        status=group["status"],
        prep=case.get("prep"),
        measure=case.get("measure"),
        delta=case.get("delta"),
        ledger=group["ledger"],
        records=group["records"],
    )


def issue(store, run_id, case):
    current = store.load(run_id)
    group = next((item for item in current["groups"] if item["case"] == case), None)
    if group is None:
        raise DomainIssue("GROUP_NOT_FOUND")
    if group["state"] == "ISSUED":
        raise DomainIssue("GROUP_FINALIZED")
    if not group["issuable"]:
        raise DomainIssue("GROUP_BLOCKED")
    return store.issue(run_id, case, pin(current, group), now())
