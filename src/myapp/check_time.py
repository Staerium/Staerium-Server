import ntplib
import datetime
import asyncio
import logging

logger = logging.getLogger(__name__)

async def check_system_time(threshold_seconds=5):
    client = ntplib.NTPClient()
    response = None
    while response == None:
        try:
            response = client.request('pool.ntp.org')  # Öffentlicher NTP-Server
            ntp_time = datetime.datetime.fromtimestamp(response.tx_time, datetime.timezone.utc)
        except Exception as e:
            logger.warning("Error fetching NTP time: %s; retrying in 5 seconds...", e)
            await asyncio.sleep(5)
    local_time = datetime.datetime.now(datetime.timezone.utc)
    
    delta = abs((ntp_time - local_time).total_seconds())
    
    if delta <= threshold_seconds:
        return True
    else:
        logger.error(
            "System time deviates too much. Ensure system time is synchronized with an NTP server."
        )
        return False
