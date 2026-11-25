"""Transactional batch state and append-only attempt history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import sqlite3


SCHEMA_VERSION = 1
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE batch (slot INTEGER PRIMARY KEY CHECK(slot = 1), manifest TEXT NOT NULL, runtime TEXT NOT NULL);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','running','done','failed')),
    attempt INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
    CHECK ((state = 'done') = (result IS NOT NULL)),
    CHECK ((state = 'failed') = (error IS NOT NULL))
);
CREATE TABLE attempts (
    job_id TEXT NOT NULL REFERENCES jobs(id), number INTEGER NOT NULL,
    started TEXT NOT NULL, finished TEXT, outcome TEXT NOT NULL
        CHECK(outcome IN ('running','interrupted','done','failed')),
    error TEXT, PRIMARY KEY (job_id, number)
);
PRAGMA user_version = 1;
COMMIT;
"""


def json_text(value):
    return json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(",",":"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def exclusive(path):
    # Keep the inode in place: deleting a lock file can allow two writers.
    with path.with_name(path.name+".lock").open("a") as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("该进度文件已有一个批量进程在写入") from exc
        yield


@contextmanager
def connect(path,writable=False):
    target = str(path) if writable else path.as_uri()+"?mode=ro"
    db = sqlite3.connect(target,uri=not writable,timeout=3,isolation_level="IMMEDIATE")
    try:
        db.row_factory = sqlite3.Row
        schema = db.execute("PRAGMA user_version").fetchone()[0]
        if writable:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
        if writable and schema==0:
            db.executescript(SCHEMA)
        elif schema!=SCHEMA_VERSION:
            raise ValueError("不支持此进度文件的版本")
        yield db
    finally:
        db.close()


def register(db,digest,runtime,jobs):
    expected = [(job["id"],i,job["kind"] if isinstance(job.get("kind"),str) else "")
                for i,job in enumerate(jobs,1)]
    with db:
        record = db.execute("SELECT manifest,runtime FROM batch WHERE slot=1").fetchone()
        if record:
            if record["manifest"]!=digest:
                raise ValueError("清单已变化，请为新清单使用新的进度文件")
            if json.loads(record["runtime"])!=runtime:
                raise ValueError("代码、OCR 或运行时版本已变化，请使用新的进度文件")
            actual = [tuple(r) for r in db.execute("SELECT id,position,kind FROM jobs ORDER BY position")]
            if actual!=expected:
                raise ValueError("进度文件的任务登记与清单不一致")
        else:
            db.execute("INSERT INTO batch VALUES (1,?,?)",(digest,json_text(runtime)))
            db.executemany("INSERT INTO jobs (id,position,kind,state) VALUES (?,?,?,'pending')",expected)


def interrupted(db):
    with db:
        ids = [row["id"] for row in db.execute("SELECT id FROM jobs WHERE state='running' ORDER BY position")]
        if ids:
            db.execute("UPDATE attempts SET outcome='interrupted',finished=? WHERE outcome='running'",(now(),))
            db.execute("UPDATE jobs SET state='pending' WHERE state='running'")
    return ids


def start(db,key):
    with db:
        updated = db.execute("""UPDATE jobs SET attempt=attempt+1,state='running',error=NULL
                               WHERE id=? AND state IN ('pending','failed') RETURNING attempt""",(key,)).fetchone()
        if not updated:
            raise ValueError(f"任务不处于可运行状态：{key}")
        number = updated["attempt"]
        db.execute("INSERT INTO attempts (job_id,number,started,outcome) VALUES (?,?,?,'running')",
                   (key,number,now()))
    return number


def finish(db,key,number,*,result=None,error=None):
    outcome = "done" if error is None else "failed"
    encoded = json_text(result) if result is not None else None
    with db:
        updated = db.execute("""UPDATE jobs SET state=?,result=?,error=?
                             WHERE id=? AND attempt=? AND state='running'""",(outcome,encoded,error,key,number))
        if updated.rowcount!=1:
            raise ValueError(f"完成记录与当前任务不一致：{key}")
        updated = db.execute("""UPDATE attempts SET outcome=?,finished=?,error=?
                             WHERE job_id=? AND number=? AND outcome='running'""",(outcome,now(),error,key,number))
        if updated.rowcount!=1:
            raise ValueError(f"完成记录与尝试历史不一致：{key}")
    return outcome


def metadata(db):
    row = db.execute("SELECT manifest,runtime FROM batch WHERE slot=1").fetchone()
    if not row:
        raise ValueError("这批任务尚未登记")
    return {"manifest_sha256":row["manifest"],"runtime":json.loads(row["runtime"])}


def summary(db):
    counts = dict(pending=0,running=0,done=0,failed=0)
    rows = []
    for row in db.execute("SELECT id,kind,state,attempt,result,error FROM jobs ORDER BY position"):
        result = json.loads(row["result"]) if row["result"] is not None else None
        counts[row["state"]] += 1
        decision = result["decision"] if result else None
        rows.append({"id":row["id"],"kind":row["kind"],"state":row["state"],"attempts":row["attempt"],
                     "decision":decision["status"] if decision else None,
                     "pixels":decision["cost"]["total"] if decision else None,
                     "ocr_calls":result["trace"]["ocr_calls"] if result else None,"error":row["error"]})
    return {**metadata(db),"counts":counts,"jobs":rows}
