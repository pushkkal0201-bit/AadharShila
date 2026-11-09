"""Durable database-backed reassessment worker.

Local worker polls for jobs; jobs are at-least-once and revision-guarded. A database
queue is deliberately simple; external production queue and horizontal scaling
are not claimed as verified.
"""
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .db import SessionLocal,init_db
from .models import Job,Application
from .service import build_assessment

def work_one(db:Session):
    # Recover stale claims after a worker crash; revision guard prevents stale writes.
    cutoff=datetime.now(timezone.utc)-timedelta(seconds=60)
    db.execute(update(Job).where(Job.status=='RUNNING',Job.claimed_at<cutoff,Job.attempts<3).values(status='QUEUED'))
    db.execute(update(Job).where(Job.status=='RUNNING',Job.claimed_at<cutoff,Job.attempts>=3).values(status='FAILED',last_error='WORKER_LEASE_EXPIRED'))
    db.commit()
    pending=db.scalar(select(Job).where(Job.status=='QUEUED').order_by(Job.created_at))
    if not pending:return None
    claimed=db.execute(update(Job).where(Job.id==pending.id,Job.status=='QUEUED').values(status='RUNNING',attempts=Job.attempts+1,claimed_at=datetime.now(timezone.utc)))
    db.commit()
    if claimed.rowcount==0:return None
    job=db.get(Job,pending.id)
    try:
        a=db.get(Application,job.application_id)
        if not a or a.revision!=job.target_revision:
            job.status='SUPERSEDED'
        else:
            build_assessment(db,a)
            job.status='COMPLETED'
        db.commit()
        return job.status
    except Exception as exc:
        db.rollback()
        job=db.get(Job,pending.id)
        if job:
            job.last_error=type(exc).__name__
            job.status='FAILED' if job.attempts>=3 else 'QUEUED'
            db.commit()
        return 'FAILED'

def loop():
    init_db()
    while True:
        try:
            with SessionLocal() as db:status=work_one(db)
            if not status:time.sleep(2)
        except KeyboardInterrupt:break
        except Exception:time.sleep(3)

if __name__=='__main__':loop()
