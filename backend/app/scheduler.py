"""Continuous-learning scheduler: `python -m backend.app.scheduler` (docker-compose service `scheduler`).

Jobs are only ENQUEUED here; the RQ worker executes them, so the API never blocks and always serves the champion.
  quarterly  full retrain            1 Jan/Apr/Jul/Oct 02:00 IST
  monthly    incremental refresh     1st of other months 03:00 IST (retrains only if CEA/PPAC/IMD/EDGAR files changed)
  daily      drift check + shadow-promotion review   04:00 IST
"""
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

TZ = "Asia/Kolkata"
TRIGGERS = {
    "full": ("Quarterly full retrain", CronTrigger(month="1,4,7,10", day=1, hour=2, timezone=TZ)),
    "incremental": ("Monthly incremental refresh", CronTrigger(month="2,3,5,6,8,9,11,12", day=1, hour=3, timezone=TZ)),
    "daily": ("Daily drift check + shadow-promotion review", CronTrigger(hour=4, timezone=TZ)),
}


def _daily() -> None:
    from redis import Redis
    from rq import Queue

    from backend.app.config import settings

    q = Queue("carbonscope", connection=Redis.from_url(settings().redis_url))
    q.enqueue("backend.app.mlops.drift_check", None, True, job_timeout=1800)
    q.enqueue("backend.app.mlops.promotion_check", None, job_timeout=600)


def next_runs() -> list[dict]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    n = datetime.now(ZoneInfo(TZ))
    return [{"job": k, "label": lab, "next_run": t.get_next_fire_time(None, n).isoformat()} for k, (lab, t) in TRIGGERS.items()]


def main() -> None:
    from backend.app import mlops

    s = BlockingScheduler(timezone=TZ)
    s.add_job(lambda: mlops.enqueue_cycle("full", "quarterly schedule"), TRIGGERS["full"][1], id="full")
    s.add_job(lambda: mlops.enqueue_cycle("incremental", "monthly schedule"), TRIGGERS["incremental"][1], id="incremental")
    s.add_job(_daily, TRIGGERS["daily"][1], id="daily")
    print("scheduler started:", next_runs(), flush=True)
    s.start()


if __name__ == "__main__":
    main()
