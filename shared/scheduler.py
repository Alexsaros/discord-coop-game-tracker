from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(
    job_defaults={
        'misfire_grace_time': 3600,     # 1 hour
    }
)


def get_scheduler() -> AsyncIOScheduler:
    return scheduler
