"""Native vector painting for the three liquid status parts.

The fixed 16px coordinate system is transformed by Qt for fractional DPRs.
Only the selected pair receives a concave neck; no raster field, blur, timer,
widget geometry change or per-pixel Python work is involved.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QRadialGradient, QPainter, QPainterPath, QTransform


_LIGHT = ((129, 104, 153), (63, 139, 121), (145, 81, 110))
_DARK = ((210, 199, 224), (121, 195, 174), (227, 185, 199))
_SATIN_LIGHT = ((126,108,154),(66,139,134),(181,116,142))
_SATIN_DARK = ((194,177,221),(130,197,186),(223,175,193))


def _clamp(value):
    return max(0., min(1., float(value)))


def _smooth(value):
    value = _clamp(value)
    return value * value * (3. - 2. * value)


def _part_color(part, island):
    base, mint, warm = _DARK if island else _LIGHT
    satin=_clamp(getattr(part,'satin',0.))
    new_base,new_mint,rose=_SATIN_DARK if island else _SATIN_LIGHT
    from theme_registry import status_rgb
    base,mint,warm=status_rgb(island)
    new_base,new_mint,rose=base,mint,warm
    base=tuple(a+(b-a)*satin for a,b in zip(base,new_base))
    mint=tuple(a+(b-a)*satin for a,b in zip(mint,new_mint))
    green = _clamp(getattr(part, 'mint', 0.))
    rosy = _clamp(getattr(part, 'rose', 0.))
    pink = _clamp(getattr(part, 'warm', 0.))
    rgb = tuple(round(((a+(b-a)*green)*(1-rosy)+r*rosy)*(1-pink)+c*pink)
                for a,b,r,c in zip(base,mint,rose,warm))
    color = QColor(*rgb)
    color.setAlphaF(_clamp(part.opacity))
    return color


def _part_path(part):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    radius, length = max(.01, part.radius), max(0., part.length)
    path.addRoundedRect(QRectF(-radius, -length - radius,
                              2. * radius, 2. * (length + radius)), radius, radius)
    if part.hole > .001:
        inner = QPainterPath()
        radius = min(radius, part.hole)
        inner.addRoundedRect(QRectF(-radius, -length - radius,
                                   2. * radius, 2. * (length + radius)), radius, radius)
        path.addPath(inner.toReversed())
    transform = QTransform()
    transform.translate(part.x, part.y)
    transform.rotate(part.angle)
    stretch=QTransform(getattr(part,'sxx',1.),getattr(part,'sxy',0.),
                       getattr(part,'sxy',0.),getattr(part,'syy',1.),0.,0.)
    path=stretch.map(path)
    return transform.map(path)


def _satin_brush(part,color):
    amount=_clamp(getattr(part,'satin',0.))
    if amount<=.00001:return color
    gradient=QRadialGradient(QPointF(part.x-part.radius*.52,part.y-part.radius*.62),part.radius*2.2)
    for position,delta in ((0.,.10),(.44,0.),(1.,-.13)):
        delta*=amount
        channels=[round(c+(255-c)*delta if delta>0 else c*(1+delta)) for c in (color.red(),color.green(),color.blue())]
        shaded=QColor(*channels);shaded.setAlpha(color.alpha());gradient.setColorAt(position,shaded)
    return gradient


def _neck(first, second, bond):
    """Return a tangent, concave neck and its smooth effective strength."""
    dx, dy = second.x - first.x, second.y - first.y
    distance = math.hypot(dx, dy)
    r1, r2 = max(.01, first.radius), max(.01, second.radius)
    # At the approved 2.2px radius, separation >=5.8px has no connector.
    # Smaller parts must not retain a long thread as they form a new glyph.
    reach = min(5.8, (r1 + r2) * (5.8 / 4.4))
    taper = 1. - _smooth(max(first.length, second.length) / 1.1)
    hollow = 1. - max(_clamp(first.hole / r1), _clamp(second.hole / r2))
    strength = (_clamp(bond) * taper * hollow
                * _smooth((reach - distance) / .65))
    if strength <= .00001 or distance <= abs(r1 - r2) + .001:
        return None
    # Tangents meet the circular contour. As strength tends to zero, both
    # attachment angles and the neck width tend to zero without a hard cutoff.
    angle = math.radians(50.) * math.sqrt(strength)
    sine, cosine = math.sin(angle), math.cos(angle)
    left, right = r1 * cosine, distance - r2 * cosine
    if right <= left:
        return None
    h1, h2 = r1 * sine, r2 * sine
    tangent = min((right - left) * .56 / max(sine, .001),
                  min(h1, h2) * .94 / max(cosine, .001))
    cx, cy = tangent * sine, tangent * cosine
    path = QPainterPath(QPointF(left, -h1))
    path.cubicTo(left + cx, -h1 + cy, right - cx, -h2 + cy, right, -h2)
    path.lineTo(right, h2)
    path.cubicTo(right - cx, h2 - cy, left + cx, h1 - cy, left, h1)
    path.closeSubpath()
    transform = QTransform()
    transform.translate(first.x, first.y)
    transform.rotate(math.degrees(math.atan2(dy, dx)))
    return transform.map(path), strength


def _neck_brush(first, second, color1, color2):
    """Keep each ball flat; blend only across the shared inter-ball neck."""
    gradient = QLinearGradient(QPointF(first.x, first.y), QPointF(second.x, second.y))
    distance = max(.001, math.hypot(second.x - first.x, second.y - first.y))
    left = first.radius / distance
    right = 1. - second.radius / distance
    if right <= left:
        middle = first.radius / max(.001, first.radius + second.radius)
        left, right = max(0., middle - .01), min(1., middle + .01)
    gradient.setColorAt(0., color1)
    gradient.setColorAt(_clamp(left), color1)
    gradient.setColorAt(_clamp(right), color2)
    gradient.setColorAt(1., color2)
    return gradient


def paint_liquid_glyph(painter, parts, island=False):
    """Paint three identity-stable parts; bond[i] joins i to (i+1)%3.

    Geometry owns the phase and pair selection. A strongest-pair fallback
    handles tiny residual bond values from a rapid state retarget without
    creating an accidental three-way liquid clump.
    """
    parts = tuple(parts)
    if not parts:
        return
    paths = tuple(_part_path(part) for part in parts)
    colors = tuple(_part_color(part, island) for part in parts)
    candidates = []
    if len(parts) > 1:
        for i, part in enumerate(parts):
            j = (i + 1) % len(parts)
            if min(part.opacity, parts[j].opacity) <= .001:
                continue
            neck = _neck(part, parts[j], getattr(part, 'bond', 0.))
            if neck is not None:
                path, strength = neck
                candidates.append((strength, i, j, path))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    joined = set()
    if candidates:
        _, i, j, neck = max(candidates, key=lambda item: item[0])
        satin=max(getattr(parts[i],'satin',0.),getattr(parts[j],'satin',0.))
        # Winding-fill overlapping subpaths in a single draw. Qt's boolean
        # united() flattens curves at logical-pixel tolerance before DPR or
        # transforms, turning these tiny circles into visibly faceted polygons.
        shape = QPainterPath()
        shape.setFillRule(Qt.FillRule.WindingFill)
        shape.addPath(paths[i])
        shape.addPath(paths[j])
        shape.addPath(neck)
        if satin>.00001:
            # Native curves form the neck; the same per-ball light is retained
            # before/while/after contact so its appearance never switches on.
            painter.fillPath(neck,_neck_brush(parts[i],parts[j],colors[i],colors[j]))
        else:
            painter.fillPath(shape, _neck_brush(parts[i], parts[j], colors[i], colors[j]))
            joined.update((i, j))
    # Equal-color capsule parts (e.g. the checkmark) share one fill so their
    # overlap does not acquire a darker edge during an opacity transition.
    groups = {}
    for i in sorted(range(len(parts)),key=lambda index:getattr(parts[index],'depth',0.)):
        path=paths[i]
        if i in joined or parts[i].opacity <= .001:
            continue
        if getattr(parts[i],'satin',0.)>.00001:
            painter.fillPath(path,_satin_brush(parts[i],colors[i]))
            continue
        key = colors[i].rgba()
        if key not in groups:
            groups[key] = QPainterPath()
            groups[key].setFillRule(Qt.FillRule.WindingFill)
        groups[key].addPath(path)
    for rgba, path in groups.items():
        painter.fillPath(path, QColor.fromRgba(rgba))
    painter.restore()
