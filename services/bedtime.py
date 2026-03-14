import asyncio
import datetime
import os

import discord
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from discord.ext.commands import Bot

from apis.discord import get_user_voice_channel
from database.db import db_session_scope
from database.models import Bedtime
from shared.exceptions import InvalidArgumentException
from shared.error_reporter import send_error_message
from shared.scheduler import get_scheduler

BEDTIME_MP3 = "bedtime.mp3"
BEDTIME_LATE_INTERVAL_MINUTES = 15


def load_bedtime_scheduler_jobs():
    with db_session_scope() as db_session:
        bedtimes = db_session.query(Bedtime).all()  # type: list[Bedtime]

    for bedtime in bedtimes:
        # Re-schedule each bedtime job
        hour = bedtime.bedtime_time.hour
        minute = bedtime.bedtime_time.minute
        get_scheduler().add_job(play_bedtime_audio, CronTrigger(hour=hour, minute=minute), args=[bedtime.user_id, bedtime.server_id], id=bedtime.scheduler_job_id)

        # Re-schedule the late bedtime reminder as well
        bedtime_late_job_id = bedtime.scheduler_job_late_id
        bedtime_original = datetime.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        bedtime_late = bedtime_original + datetime.timedelta(minutes=BEDTIME_LATE_INTERVAL_MINUTES)
        hour_late = bedtime_late.hour
        minute_late = bedtime_late.minute
        get_scheduler().add_job(play_bedtime_audio, CronTrigger(hour=hour_late, minute=minute_late), args=[bedtime.user_id, bedtime.server_id, True], id=bedtime_late_job_id)


async def play_audio(bot: Bot, voice_channel: discord.VoiceChannel, audio_path):
    try:
        voice_client = await voice_channel.connect()
    except Exception as e:
        await send_error_message(bot, f"Error: failed to connect to voice channel. {e}")
        return

    try:
        # Wait a little to give the "joined channel" sound effect time to go away before we start playing sound
        await asyncio.sleep(0.5)
        voice_client.play(discord.FFmpegPCMAudio(audio_path))

        while voice_client.is_playing():
            await asyncio.sleep(1)
    except Exception as e:
        await send_error_message(bot, f"Error: failed to play audio. {e}")

    await voice_client.disconnect()


async def play_bedtime_audio(bot: Bot, user_id: int, server_id: int, late_reminder: bool = False):
    voice_channel = await get_user_voice_channel(bot, user_id, server_id)
    if voice_channel is None:
        return

    user_specific_bedtime_mp3 = f"bedtime_"
    if late_reminder:
        user_specific_bedtime_mp3 += "late_"
    user_specific_bedtime_mp3 += f"{user_id}.mp3"

    # If the user has a unique bedtime mp3, play that
    if os.path.isfile(user_specific_bedtime_mp3):
        await play_audio(bot, voice_channel, user_specific_bedtime_mp3)
    else:
        if late_reminder:
            # If the user has not set an mp3 for the late reminder, do not play anything
            return
        else:
            # User has not set an mp3, so play the generic mp3
            await play_audio(bot, voice_channel, BEDTIME_MP3)


async def set_bedtime(bot: Bot, server_id: int, user_id: int, bedtime: str):
    try:
        bedtime_split = bedtime.split(":")
        hour = int(bedtime_split[0])
        minute = 0 if len(bedtime_split) == 1 else int(bedtime_split[1])
        assert hour < 24
        assert minute < 60
    except (ValueError, IndexError, AssertionError):
        raise InvalidArgumentException("Invalid time given.")

    with db_session_scope() as db_session:
        bedtime_old = db_session.get(Bedtime, (user_id, server_id))    # type: Bedtime

        # First stop any existing bedtimes for this user
        if bedtime_old is not None:
            try:
                get_scheduler().remove_job(bedtime_old.scheduler_job_id)
            except JobLookupError as e:
                await send_error_message(bot, f"Error! Unable to remove scheduled bedtime job with id {bedtime_old.scheduler_job_id}. {e}")
            try:
                get_scheduler().remove_job(bedtime_old.scheduler_job_late_id)
            except JobLookupError as e:
                await send_error_message(bot, f"Error! Unable to remove scheduled late bedtime job with id {bedtime_old.scheduler_job_late_id}. {e}")

        # If a negative value was given, remove the bedtime alarm
        if hour < 0 or minute < 0:
            if bedtime_old is not None:
                db_session.delete(bedtime_old)
        else:
            # Schedule the new bedtime
            job = get_scheduler().add_job(play_bedtime_audio, CronTrigger(hour=hour, minute=minute),
                                          args=[user_id, server_id], id=f"{server_id}_bedtime_{user_id}")

            # Also schedule a later reminder
            bedtime_original = datetime.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            bedtime_late = bedtime_original + datetime.timedelta(minutes=BEDTIME_LATE_INTERVAL_MINUTES)
            hour_late = bedtime_late.hour
            minute_late = bedtime_late.minute
            job_late = get_scheduler().add_job(play_bedtime_audio, CronTrigger(hour=hour_late, minute=minute_late),
                                               args=[user_id, server_id, True], id=f"{server_id}_bedtime_late_{user_id}")

            # Save the new bedtime
            bedtime_new = Bedtime(
                user_id=user_id,
                server_id=server_id,
                bedtime_time=datetime.time(hour=hour, minute=minute),
                scheduler_job_id=job.id,
                scheduler_job_late_id=job_late.id,
            )
            db_session.add(bedtime_new)

