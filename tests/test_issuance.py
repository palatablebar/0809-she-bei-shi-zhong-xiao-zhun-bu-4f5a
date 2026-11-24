import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.review.service import execute, issue
from tests.conftest import csv_data


def group(run, case):
    return next(item for item in run["groups"] if item["case"] == case)


def test_group_ledger_reconciles_four_record_kinds(store, dirty):
    run = execute(store, dirty)
    first = group(run, "0001")
    assert first["ledger"] == {"input": 5, "accepted": 4, "isolated": 1, "rejected": 0}
    assert first["records"]["accepted"] == ["000101", "000102", "000103", "000104"]
    assert [row["record"] for row in first["records"]["isolated"]] == ["000102"]
    assert first["records"]["isolated"][0]["reason"] == "DUPLICATE_REPLAY"


def test_problem_group_blocks_only_itself_and_lists_record_keys(store, dirty):
    run = execute(store, dirty)
    third = group(run, "0003")
    assert third["status"] == "OUTSIDE_SYNC" and not third["issuable"]
    assert third["holds"] == [
        {"code": "OUTSIDE_SYNC", "records": ["000301", "000302", "000303", "000304"]}
    ]
    assert group(run, "0002")["holds"] == []


def test_unattributed_isolation_prevents_claiming_groups_verified(store, dirty):
    run = execute(store, dirty)
    assert [row["record"] for row in run["orphans"]] == ["ERR1", "ERR2", "ERR3", "ERR3"]
    assert all(not item["issuable"] for item in run["groups"])


def test_clean_groups_are_independently_issuable(store, clean):
    run = execute(store, clean)
    assert [item["issuable"] for item in run["groups"]] == [True, True]
    assert run["orphans"] == []


def test_issue_pins_group_evidence(store, clean):
    run = execute(store, clean)
    output = issue(store, run["id"], "0001")
    issued = group(output, "0001")
    assert (issued["state"], group(output, "0002")["state"]) == ("ISSUED", "PENDING")
    evidence = issued["evidence"]
    assert evidence["schema"] == "group-evidence/1"
    assert evidence["manifest"]["sha256"] == run["report"]["manifest"]["sha256"]
    assert evidence["measure"]["value"] == 220
    assert evidence["ledger"] == {"input": 4, "accepted": 4, "isolated": 0, "rejected": 0}
    assert issued["issued"] is not None


def test_same_source_rerun_adds_no_group_results(store, clean):
    first = execute(store, clean)
    issued = issue(store, first["id"], "0001")
    second = execute(store, clean)
    assert second == issued
    assert [item["case"] for item in second["groups"]] == ["0001", "0002"]
    assert group(second, "0001")["issued"] == group(issued, "0001")["issued"]


def test_supplement_cannot_rewrite_issued_group(store, clean):
    run = execute(store, clean)
    pinned = group(issue(store, run["id"], "0001"), "0001")["evidence"]
    supplement = csv_data(
        [
            ["000101", "0001", "sync", "200", "280", "0", "交接明细"],
            ["000102", "0001", "reading", "150", "222", "4", "复核底稿"],
            ["000103", "0001", "sync", "100", "160", "0", "补录记录"],
            ["000104", "0001", "check", "0", "220", "0", "已对照来源"],
            ["000105", "0001", "reading", "160", "230", "4", "补录记录"],
        ]
    )
    rerun = execute(store, supplement)
    assert rerun["id"] != run["id"]
    original = store.load(run["id"])
    assert group(original, "0001")["evidence"] == pinned
    assert group(original, "0001")["evidence"]["measure"]["value"] == 220
    assert group(rerun, "0001")["state"] == "PENDING"


def test_blocked_issue_preserves_batch(store, dirty):
    run = execute(store, dirty)
    with pytest.raises(DomainIssue, match="GROUP_BLOCKED"):
        issue(store, run["id"], "0003")
    with pytest.raises(DomainIssue, match="GROUP_NOT_FOUND"):
        issue(store, run["id"], "9999")
    kept = store.load(run["id"])
    assert kept["revision"] == 0 and len(kept["groups"]) == 4
    assert all(item["state"] == "PENDING" for item in kept["groups"])


def test_failed_submit_rolls_back_without_losing_records(store, clean):
    run = execute(store, clean)
    with pytest.raises(TypeError):
        store.issue(run["id"], "0001", {"bad": object()}, "now")
    kept = store.load(run["id"])
    assert kept["id"] == run["id"] and len(kept["groups"]) == 2
    assert all(item["state"] == "PENDING" for item in kept["groups"])
    assert len(store.list()) == 1


def test_issued_group_is_final(store, clean):
    run = execute(store, clean)
    issue(store, run["id"], "0001")
    with pytest.raises(DomainIssue, match="GROUP_FINALIZED"):
        issue(store, run["id"], "0001")


def test_parallel_issue_has_one_winner(store, clean):
    run = execute(store, clean)
    start = Barrier(2)

    def attempt(_):
        start.wait(3)
        try:
            return issue(store, run["id"], "0001")["id"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(attempt, range(2)))
    assert results.count(run["id"]) == 1 and results.count("GROUP_FINALIZED") == 1
    assert group(store.load(run["id"]), "0001")["state"] == "ISSUED"


def test_issue_http_flow(client):
    run = client.post("/api/runs", data={"sample": "clean"}).json
    assert client.get("/api/runs/" + run["id"]).json["groups"][0]["issuable"] is True
    output = client.post(f"/api/runs/{run['id']}/groups/0001/issue")
    assert output.status_code == 200
    assert group(output.json, "0001")["state"] == "ISSUED"
    again = client.post(f"/api/runs/{run['id']}/groups/0001/issue")
    assert again.status_code == 409 and again.json["code"] == "GROUP_FINALIZED"


def test_issue_http_rejections(client):
    run = client.post("/api/runs", data={"sample": "dirty"}).json
    blocked = client.post(f"/api/runs/{run['id']}/groups/0003/issue")
    assert blocked.status_code == 409 and blocked.json["code"] == "GROUP_BLOCKED"
    missing = client.post(f"/api/runs/{run['id']}/groups/9999/issue")
    assert missing.status_code == 404 and missing.json["code"] == "GROUP_NOT_FOUND"
    orphan_blocked = client.post(f"/api/runs/{run['id']}/groups/0002/issue")
    assert orphan_blocked.status_code == 409
    kept = client.get("/api/runs/" + run["id"]).json
    assert all(item["state"] == "PENDING" for item in kept["groups"])


def test_unknown_run_issue_is_404(client):
    assert client.post("/api/runs/unknown/groups/0001/issue").status_code == 404


def test_evidence_packet_lists_groups_and_orphans(store, dirty, clean):
    dirty_packet = json.loads(artifact(execute(store, dirty)))
    assert [row["record"] for row in dirty_packet["orphans"]] == [
        "ERR1",
        "ERR2",
        "ERR3",
        "ERR3",
    ]
    assert {item["case"] for item in dirty_packet["groups"]} == {
        "0001",
        "0002",
        "0003",
        "0004",
    }
    run = execute(store, clean)
    issue(store, run["id"], "0002")
    packet = json.loads(artifact(store.load(run["id"])))
    issued = next(item for item in packet["groups"] if item["case"] == "0002")
    assert issued["state"] == "ISSUED" and issued["evidence"]["case"] == "0002"
    assert artifact(store.load(run["id"])) == artifact(store.load(run["id"]))
