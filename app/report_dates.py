"""Local calendar periods shared by report navigation and cost queries."""
from calendar import monthrange
from datetime import date, datetime, timedelta


MONTH='30d'
WEEK='7d'
DAY='yesterday'
CALENDAR_PERIODS=(MONTH,WEEK,DAY)


def date_bounds(period, day):
    if period==MONTH:
        return day.replace(day=1),day.replace(day=monthrange(day.year,day.month)[1])
    if period==WEEK:
        first=day-timedelta(days=day.weekday())
        return first,first+timedelta(days=6)
    return day,day


def range_key(bounds):
    return 'calendar:'+':'.join(day.isoformat() for day in bounds)


def parse_range_key(value):
    if not value.startswith('calendar:'):return None
    return tuple(date.fromisoformat(day) for day in value.split(':')[1:])


def period_text(period, bounds, *, cost=False, full=False):
    if bounds is None:return '全部时间'
    first,last=bounds
    if period==MONTH:return f'{first.year} 年 {first.month} 月' if full or not cost else f'{first.month}月'
    if period==DAY:return f'{first.year}.{first.month}.{first.day}'
    sep='.' if cost else '/'
    def part(value):
        prefix=f'{value.year}{sep}' if first.year!=last.year else ''
        return f'{prefix}{value.month}{sep}{value.day}'
    return f'{part(first)} – {part(last)}'


def quota_span(cycle):
    start=cycle['start']
    end=cycle.get('end') if cycle.get('closed') else cycle.get('reset_at')
    if not end or end<=start:end=max(start,cycle.get('through') or start)
    return datetime.fromtimestamp(start),datetime.fromtimestamp(end)


def quota_days(cycle):
    first,last=quota_span(cycle)
    # A reset exactly at midnight belongs to the next cycle's date.
    return first.date(),(last-timedelta(microseconds=1)).date() if last>first else first.date()


def quota_text(cycle):
    first,last=quota_span(cycle)
    pattern='%Y/%m/%d %H:%M' if first.year!=last.year else '%m/%d %H:%M'
    if not cycle.get('closed') and (cycle.get('reset_at') or 0)<=cycle['start']:
        return f'{first:{pattern}} – 至今'
    return f'{first:{pattern}} – {last:{pattern}}'
