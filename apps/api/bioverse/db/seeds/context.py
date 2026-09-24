"""What every seed module receives: the clinic's time zone and date helpers relative to today."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SeedContext:
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(os.getenv("BIOVERSE_CLINIC_TZ", "America/New_York")))

    @property
    def today(self) -> date:
        return datetime.now(self.tz).date()

    def days(self, n: int) -> date:
        """Today plus n days (negative for the past)."""
        return self.today + timedelta(days=n)

    def at(self, day: date, hh: int, mm: int = 0) -> datetime:
        """A clinic-local timestamp on `day`."""
        return datetime.combine(day, time(hh, mm), tzinfo=self.tz)
