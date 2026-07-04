"""Time MCP Server."""
from datetime import datetime, timezone
import time as _time
import pytz
from .base import BaseMCPServer


class TimeServer(BaseMCPServer):
    def __init__(self, default_timezone: str = "UTC"):
        self.default_tz = default_timezone

    def current_time(self, timezone: str = None) -> dict:
        tz_name = timezone or self.default_tz
        try:
            import pytz
            tz = pytz.timezone(tz_name)
            now = datetime.now(tz)
        except Exception:
            now = datetime.now(pytz.UTC)
            tz_name = "UTC"
        return {
            "datetime": now.isoformat(),
            "timezone": tz_name,
            "timestamp": int(now.timestamp()),
            "readable": now.strftime("%A, %B %d %Y %H:%M:%S %Z"),
        }

    def convert_timezone(self, dt_str: str, from_tz: str, to_tz: str) -> dict:
        try:
            import pytz
            from dateutil import parser
            from_zone = pytz.timezone(from_tz)
            to_zone = pytz.timezone(to_tz)
            dt = parser.parse(dt_str)
            if dt.tzinfo is None:
                dt = from_zone.localize(dt)
            converted = dt.astimezone(to_zone)
            return {"original": dt_str, "converted": converted.isoformat(), "to_timezone": to_tz}
        except Exception as e:
            return {"error": str(e)}
