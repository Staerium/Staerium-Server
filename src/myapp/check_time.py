import ntplib
import datetime
import asyncio

async def check_system_time(threshold_seconds=5):
    client = ntplib.NTPClient()
    response = None
    while response == None:
        try:
            response = client.request('pool.ntp.org')  # Öffentlicher NTP-Server
            ntp_time = datetime.datetime.fromtimestamp(response.tx_time, datetime.timezone.utc)
        except Exception as e:
            print(f"Error fetching NTP time: {e}; retrying in 5 seconds...")
            await asyncio.sleep(5)
    local_time = datetime.datetime.now(datetime.timezone.utc)
    
    delta = abs((ntp_time - local_time).total_seconds())
    
    if delta <= threshold_seconds:
        return True
    else:
        print("System time deviates too much! Please ensure that the system time is synchronized with an NTP server.")
        return False