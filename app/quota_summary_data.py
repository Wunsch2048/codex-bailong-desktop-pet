"""Small, truthful display values for account quota and local daily usage."""
import math
import time
from datetime import date, datetime

from reset_watch import BEIJING, epoch
from token_calendar import compact_tokens


def _countdown(seconds):
    minutes = max(1, math.ceil(seconds / 60))
    days, hours = divmod(minutes // 60, 24)
    if days:
        value = f'{days}天' + (f'{hours}时' if hours else '')
    elif hours:
        value = f'{hours}时' + (f'{minutes % 60}分' if minutes % 60 else '')
    else:
        value = f'{minutes}分'
    return value + '后重置'


def _percentage(value):
    # Keep the small card readable without falsely showing empty/full quota.
    if 0 < value < 1:
        return '<1%'
    if 99 < value < 100:
        return '>99%'
    return f'{value:.1f}'.rstrip('0').rstrip('.') + '%'


def quota_items(windows, now=None):
    """At most two windows; an elapsed reset invalidates the old percentage."""
    now = time.time() if now is None else now
    source = [w for w in windows if isinstance(w, dict)] if isinstance(windows, (list, tuple)) else []
    ordered = sorted(source, key=lambda w: {'5小时': 0, '一周': 1}.get(w.get('name'), 2)
                     if isinstance(w.get('name'), str) else 2)
    result = []
    seen = set()
    for window in ordered:
        name = window.get('name')
        name = name if isinstance(name, str) and name.strip() else '额度'
        if name in seen:
            continue
        seen.add(name)
        stamp = epoch(window.get('resetsAt'))
        expired = stamp is not None and stamp <= now
        value = window.get('remaining')
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and 0 <= value <= 100 and math.isfinite(value) and not expired)
        remaining = float(value) if valid else None
        display = _percentage(remaining) if valid else '—'
        reset_text = ('待刷新' if expired else _countdown(stamp - now)) if stamp is not None else '重置时间未知'
        description = f'{name}剩余额度：' + (f'{remaining:g}%' if valid else '暂不可用')
        if stamp is not None:
            precise = datetime.fromtimestamp(stamp, BEIJING).strftime('%Y-%m-%d %H:%M:%S')
            description += f'\n重置时间：{precise}（北京时间）'
        else:
            description += '\n重置时间未知。'
        if expired:
            description += '\n重置时间已到，等待刷新额度；旧值不代表当前剩余量。'
        if not valid:
            description += '\n空轨道表示未知，不代表 0%。'
        label = {'5小时': '5h剩余', '一周': '周剩余'}.get(name, name if len(name) <= 5 else name[:4] + '…')
        result.append(dict(id='quota:' + name, name=name, label=label, remaining=remaining,
                           progress=remaining / 100 if valid else None, display=display,
                           low=valid and remaining <= 15, expired=expired, reset_at=stamp,
                           reset_text=reset_text, description=description))
        if len(result) == 2:
            break
    return result or [dict(id='quota:unknown', name='额度', label='额度剩余', remaining=None,
                          progress=None, display='—', low=False, expired=False, reset_at=None,
                          reset_text='重置时间未知', description='账户额度尚未取得。\n空轨道表示未知，不代表 0%。')]


def today_tokens(tokens, now=None, live=None):
    """Use the same local calendar day as TokenUsageIndex, never a peak ratio."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    snapshot = tokens if isinstance(tokens, dict) else {}
    partial = snapshot.get('partial') is True
    days = snapshot.get('days')
    known = (bool(snapshot) and not snapshot.get('unavailable')
             and snapshot.get('month') == today.strftime('%Y-%m') and isinstance(days, dict))
    count = 0
    if known:
        for key, value in days.items():
            if not isinstance(key, str):
                continue
            try:
                day = date.fromisoformat(key)
            except ValueError:
                continue
            if key != day.isoformat() or (day.year, day.month) != (today.year, today.month) or day > today:
                continue
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            if day == today:
                # Missing today is zero; a corrupt present value must not become zero.
                known = valid
                count = value if valid else 0
    if isinstance(live,dict) and live.get('day')==today.isoformat() and type(live.get('count')) is int and live['count']>=0:
        count=live['count'];known=True;partial=partial or bool(live.get('partial'))
    if known:
        try:
            display = compact_tokens(count)
        except OverflowError:
            # JSON integers have arbitrary precision; oversized counters must
            # not crash the UI during compact formatting.
            display = '>999T'
        description = f'今日 Token：{count:,}\n本机 Codex 日志；输入含缓存，输出含推理。此数值不表示套餐额度。'
    else:
        display = '待统计'
        description = '今日 Token 尚未取得有效统计。\n统计口径：本机 Codex 日志；输入含缓存，输出含推理。'
    if partial:
        description += '\n部分日志暂不可读，仅包含已读取记录。'
    return dict(display=display, count=count if known else None, known=known, partial=partial, description=description)
