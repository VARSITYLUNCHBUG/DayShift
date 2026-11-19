"""Date formats for the admin and the staff pages.

Times are stored and shown in UTC (TIME_ZONE), while Discord shows each viewer their own time, so
every date with a time says "UTC" to keep the two from looking like they disagree.
"""

DATETIME_FORMAT = "j M Y, H:i T"
SHORT_DATETIME_FORMAT = "d/m/Y H:i T"
