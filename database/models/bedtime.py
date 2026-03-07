from sqlalchemy import Column, Integer, String, ForeignKey, Time

from database.db import BaseModel


class Bedtime(BaseModel):
    __tablename__ = "bedtimes"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)

    bedtime_time = Column(Time, nullable=False)
    scheduler_job_id = Column(String)
    scheduler_job_late_id = Column(String)
