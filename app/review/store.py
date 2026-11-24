import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue
from app.modules.reconcile import ledgers

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);
CREATE TABLE IF NOT EXISTS issuance (
    run_id TEXT NOT NULL, device_case TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING', evidence TEXT, issued TEXT,
    PRIMARY KEY (run_id, device_case)
);"""


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            yield db

    def register(self, run_id, report):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    json.dumps(report, ensure_ascii=False),
                    report["manifest"]["created"],
                ),
            )
            db.executemany(
                "INSERT INTO issuance(run_id,device_case) VALUES (?,?) ON CONFLICT DO NOTHING",
                [(run_id, item["case"]) for item in report.get("groups", [])],
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            states = db.execute(
                "SELECT * FROM issuance WHERE run_id=?", (run_id,)
            ).fetchall()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        report = result["report"]
        groups = report.get("groups")
        orphans = report.get("orphans")
        if groups is None or orphans is None:
            groups, orphans = ledgers(report["intake"], report["cases"])
        pinned = {state["device_case"]: dict(state) for state in states}
        result["groups"] = [
            dict(
                item,
                state=pinned.get(item["case"], {}).get("state", "PENDING"),
                issued=pinned.get(item["case"], {}).get("issued"),
                evidence=(
                    json.loads(pinned[item["case"]]["evidence"])
                    if pinned.get(item["case"], {}).get("evidence")
                    else None
                ),
            )
            for item in groups
        ]
        result["orphans"] = orphans
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)

    def issue(self, run_id, case, evidence, now):
        with self.connect() as db:
            db.execute(
                "INSERT INTO issuance(run_id,device_case) VALUES (?,?) ON CONFLICT DO NOTHING",
                (run_id, case),
            )
            cursor = db.execute(
                "UPDATE issuance SET state='ISSUED',evidence=?,issued=? WHERE run_id=? AND device_case=? AND state='PENDING'",
                (
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    now,
                    run_id,
                    case,
                ),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("GROUP_FINALIZED")
        return self.load(run_id)
