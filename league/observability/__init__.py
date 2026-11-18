"""Prometheus metrics for the web process: request metrics and the league's own gauges.

The bot and the scheduler export theirs from `bot.metrics`, on `METRICS_PORT`. Nothing here
imports `bot`, so the web process never loads Discord code.
"""
