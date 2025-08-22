from datetime import date, timedelta

def day_range(period: str) -> tuple[str,str]:
    today = date.today()
    if period == "day":
        start = today
    elif period == "week":
        start = today - timedelta(days=6)
    elif period == "month":
        start = today - timedelta(days=29)
    else:
        start = today
    return (start.isoformat(), today.isoformat())
