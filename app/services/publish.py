import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.config import DB_PATH, ROOT

logger = logging.getLogger("quant.publish")

REPO = "18916970831-blip/jihuanshe-quant"
BRANCH = "main"
DB_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/data/market.db"
COMMITS_URL = f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&path=data/market.db&per_page=1"
SYNC_URL = os.environ.get("QUANT_SYNC_URL", "https://jihuanshe-quant.onrender.com/api/sync")

DEBOUNCE_SECONDS = 15
MAX_WAIT_SECONDS = 60
POLL_SECONDS = 90

_lock = threading.Lock()
_push_lock = threading.Lock()
_timer: threading.Timer | None = None
_generation = 0
_waiting_since: float | None = None
_last_sha: str | None = None
_last_check = 0.0
_state = "idle"
_detail = ""


def publish_enabled() -> bool:
    return os.environ.get("QUANT_PUBLISH") == "1"


def pull_enabled() -> bool:
    return os.environ.get("QUANT_SHARE") == "1" and not publish_enabled()


def publish_status() -> str | None:
    if not publish_enabled():
        return None
    return _state


def schedule_publish() -> None:
    """Queue a public update. A burst of entries becomes one push after a short pause."""
    if not publish_enabled():
        return
    global _timer, _generation, _waiting_since
    with _lock:
        now = time.time()
        if _waiting_since is None:
            _waiting_since = now
        _generation += 1
        generation = _generation
        delay = 0.5 if now - _waiting_since >= MAX_WAIT_SECONDS and _state != "pushing" else DEBOUNCE_SECONDS
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(delay, lambda: _publish_safe(generation))
        _timer.daemon = True
        _timer.start()
        _set_state("waiting", "")


def publish_if_dirty() -> None:
    if not publish_enabled():
        return
    if _working_tree_dirty():
        schedule_publish()


def pull_once() -> dict:
    global _last_sha, _last_check
    if publish_enabled():
        return {"updated": False, "reason": "publisher"}
    now = time.time()
    if now - _last_check < 20:
        return {"updated": False, "reason": "recent"}
    _last_check = now
    try:
        sha = _remote_sha()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("could not read remote database version: %s", exc)
        return {"updated": False, "error": "remote"}
    if sha == _last_sha:
        return {"updated": False, "sha": sha}
    dest = DB_PATH.with_name("market.db.download")
    try:
        _download(sha, dest)
        if not sqlite_ok(dest):
            dest.unlink(missing_ok=True)
            return {"updated": False, "error": "invalid"}
        if DB_PATH.exists() and _file_hash(dest) == _file_hash(DB_PATH):
            dest.unlink(missing_ok=True)
            _last_sha = sha
            return {"updated": False, "sha": sha, "reason": "same"}
        from sqlalchemy import func, select

        from app.database import SessionLocal, replace_database
        from app.models import Trade
        from app.services.alerts import scan_alerts

        replace_database(dest)
        db = SessionLocal()
        try:
            scan_alerts(db)
            count = db.scalar(select(func.count()).select_from(Trade)) or 0
            as_of = db.scalar(select(func.max(Trade.trade_date)))
        finally:
            db.close()
    except Exception:
        logger.exception("database refresh failed")
        dest.unlink(missing_ok=True)
        return {"updated": False, "error": "refresh"}
    _last_sha = sha
    logger.info("public database updated to %s", sha[:7])
    return {"updated": True, "sha": sha, "trades": count, "as_of": as_of.isoformat() if as_of else None}


def pull_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            pull_once()
        except Exception:
            logger.exception("public refresh failed")
        stop.wait(POLL_SECONDS)


def sqlite_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 100:
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        check = con.execute("PRAGMA integrity_check").fetchone()
        count = con.execute("SELECT COUNT(*) FROM trades").fetchone()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return bool(check and check[0] == "ok" and count and count[0] > 0)


def _publish_safe(generation: int | None = None) -> None:
    if not _push_lock.acquire(blocking=False):
        _retry()
        return
    try:
        _set_state("pushing", "")
        pushed = _publish()
    except Exception as exc:
        logger.exception("public sync failed")
        _set_state("error", str(exc).splitlines()[-1][:180] if str(exc) else "sync failed")
        _retry()
        return
    finally:
        _push_lock.release()
    with _lock:
        current = _generation
        if generation is None or current == generation:
            global _waiting_since
            _waiting_since = None
    if generation is not None and current != generation:
        _set_state("waiting", "")
        return
    _set_state("ok" if pushed else "idle", "")
    if pushed:
        _ping()


def _publish() -> bool:
    _checkpoint()
    if not _git(["add", "--", "data/market.db"]):
        raise RuntimeError("git add failed")
    if not _cached_changes():
        return False
    if not _git(["commit", "-m", "Sync newly entered trades to the public site.", "--", "data/market.db"]):
        raise RuntimeError("git commit failed")
    if not _git(["push", "origin", "HEAD"], timeout=90):
        raise RuntimeError("git push failed")
    return True


def _retry() -> None:
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(30, _publish_safe)
        _timer.daemon = True
        _timer.start()


def _checkpoint() -> None:
    from app.database import engine

    raw = engine.raw_connection()
    try:
        raw.cursor().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw.commit()
    finally:
        raw.close()


def _working_tree_dirty() -> bool:
    result = _run(["git", "status", "--porcelain", "--", "data/market.db"])
    return bool(result and result.stdout.strip())


def _cached_changes() -> bool:
    result = _run(["git", "diff", "--cached", "--quiet", "--", "data/market.db"])
    return bool(result and result.returncode == 1)


def _git(args: list[str], timeout: int = 30) -> bool:
    result = _run(["git", *args], timeout=timeout)
    if result is None or result.returncode != 0:
        detail = ""
        if result is not None:
            detail = (result.stderr or result.stdout or "").strip()
        logger.error("git %s failed: %s", " ".join(args), detail)
        if detail:
            raise RuntimeError(detail)
        return False
    return True


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("%s: %s", args[0], exc)
        return None


def _ping() -> None:
    request = urllib.request.Request(SYNC_URL, data=b"{}", method="POST", headers={"Content-Type": "application/json", "User-Agent": "jihuanshe-quant"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response.read()
    except Exception as exc:
        logger.warning("public site will catch up on its next check: %s", exc)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _remote_sha() -> str:
    request = urllib.request.Request(COMMITS_URL, headers={"User-Agent": "jihuanshe-quant", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload[0]["sha"]


def _download(sha: str, dest: Path) -> None:
    request = urllib.request.Request(f"{DB_URL}?v={sha}", headers={"User-Agent": "jihuanshe-quant"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if len(data) > 20 * 1024 * 1024 or not data.startswith(b"SQLite format 3"):
        raise RuntimeError("downloaded file is not a database")
    dest.write_bytes(data)


def _set_state(status: str, detail: str) -> None:
    global _state, _detail
    _state = status
    _detail = detail
