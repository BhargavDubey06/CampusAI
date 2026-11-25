"""Single-process scheduler for reminder due-state updates.
For production multi-worker deployments, use an external scheduler/worker instead.
"""
import logging, threading, time
from datetime import datetime, timezone
from backend import database as db
from backend.features import init_feature_tables
log=logging.getLogger('campusai.reminders')
_started=False
_lock=threading.Lock()
def _tick():
    try:
        init_feature_tables()
        now=datetime.now(timezone.utc)
        with db.get_conn() as c:
            rows=c.execute("SELECT id,remind_at FROM reminders WHERE status='scheduled'").fetchall()
            due=[]
            for row in rows:
                try:
                    target=datetime.fromisoformat(row['remind_at'])
                    if target.tzinfo is None: target=target.astimezone()
                    if target.astimezone(timezone.utc)<=now: due.append(row['id'])
                except (ValueError,TypeError):
                    log.warning('Invalid reminder time for reminder ID %s',row['id'])
            if due:
                placeholders=','.join('?' for _ in due)
                c.execute(f"UPDATE reminders SET status='triggered',triggered_at=? WHERE id IN ({placeholders})",(now.astimezone().isoformat(),*due))
    except Exception:
        log.exception('Reminder scheduler tick failed')
def _loop():
    while True:
        _tick();time.sleep(60)
def start_scheduler():
    global _started
    with _lock:
        if _started:return
        _started=True
        threading.Thread(target=_loop,name='campusai-reminder-scheduler',daemon=True).start()
