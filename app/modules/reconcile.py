from collections import Counter

ISOLATED_REASONS = {"DUPLICATE_CONFLICT", "DUPLICATE_REPLAY"}


def ledgers(intake, cases):
    """按设备组核对输入、采信、隔离与被拒记录。

    隔离行按 case 归属设备组；无法归属的行列入 orphans，
    存在孤儿行时任何组都不能视为已完整核对。
    """
    attributed = {case["case"]: {"isolated": [], "rejected": []} for case in cases}
    orphans = []
    for row in intake["isolation"]:
        bucket = attributed.get(row["case"])
        if bucket is None:
            orphans.append(row)
        else:
            bucket["isolated" if row["reason"] in ISOLATED_REASONS else "rejected"].append(row)
    items = []
    for case in cases:
        key = case["case"]
        isolated = [
            dict(record=row["record"], line=row["line"], reason=row["reason"])
            for row in attributed[key]["isolated"]
        ]
        rejected = [
            dict(record=row["record"], line=row["line"], reason=row["reason"])
            for row in attributed[key]["rejected"]
        ]
        holds = []
        if case["status"] != "READY":
            holds.append(dict(code=case["status"], records=list(case["records"])))
        if isolated:
            holds.append(dict(code="ISOLATED_RECORDS", records=[r["record"] for r in isolated]))
        if rejected:
            holds.append(dict(code="REJECTED_RECORDS", records=[r["record"] for r in rejected]))
        items.append(
            dict(
                case=key,
                status=case["status"],
                issuable=not holds and not orphans,
                ledger=dict(
                    input=len(case["records"]) + len(isolated) + len(rejected),
                    accepted=len(case["records"]),
                    isolated=len(isolated),
                    rejected=len(rejected),
                ),
                records=dict(
                    accepted=list(case["records"]), isolated=isolated, rejected=rejected
                ),
                holds=holds,
            )
        )
    return items, orphans


def balance(intake, cases):
    accounted = (
        intake["accepted"] + intake["rejected"] + intake["blank"] + intake["repeated"]
    )
    status = Counter(case["status"] for case in cases)
    ready = status.pop("READY", 0)
    observed = sum(len(case["records"]) for case in cases)
    return dict(
        input=intake["input"],
        accepted=intake["accepted"],
        isolated=intake["rejected"],
        ignored=intake["blank"] + intake["repeated"],
        accounted=accounted,
        balanced=accounted == intake["input"] and observed == intake["accepted"],
        ready=ready,
        pending=len(cases) - ready,
        issues=dict(sorted(status.items())),
        releasable=bool(cases)
        and ready == len(cases)
        and not intake["rejected"]
        and accounted == intake["input"]
        and observed == intake["accepted"],
    )
