"""Vencimientos de los contratos de futuros (último día de negociación).

Las fechas se calculan con la regla de cada mercado, sin descargar nada:

    third_wednesday  N días hábiles antes del tercer miércoles del mes del
                     contrato (`offset`). Divisas del CME y Dollar Index: 2;
                     dólar canadiense: 1.
    day_15           día hábil anterior al 15 del mes del contrato. Granos y
                     oleaginosas del CBOT.
    month_end        N días hábiles antes del último día hábil del mes del
                     contrato (`offset`). Café: 8; cacao: 11; algodón: 16.
    prior_month_end  último día hábil del mes anterior al del contrato.
                     Azúcar nº 11.

El calendario de festivos es el general de los mercados de EE. UU. En algún
festivo poco habitual la fecha real puede diferir en un día.
"""

import bisect
import datetime as dt

MONTH_CODES = "FGHJKMNQUVXZ"  # enero ... diciembre


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return dt.date(year, month, day)


def _nth_weekday(year, month, weekday, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


_cache = {}


def holidays(year):
    if year not in _cache:
        days = {
            _observed(dt.date(year, 1, 1)),
            _nth_weekday(year, 2, 0, 3),                 # Presidents' Day
            _easter(year) - dt.timedelta(days=2),        # Viernes Santo
            _last_weekday(year, 5, 0),                   # Memorial Day
            _observed(dt.date(year, 7, 4)),
            _nth_weekday(year, 9, 0, 1),                 # Labor Day
            _nth_weekday(year, 11, 3, 4),                # Thanksgiving
            _observed(dt.date(year, 12, 25)),
        }
        if year >= 1998:
            days.add(_nth_weekday(year, 1, 0, 3))        # Martin Luther King
        if year >= 2022:
            days.add(_observed(dt.date(year, 6, 19)))    # Juneteenth
        _cache[year] = days
    return _cache[year]


def is_business_day(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def back(d, n):
    """Retrocede n días hábiles desde d (sin contar d)."""
    while n > 0:
        d -= dt.timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


def last_business_day(year, month):
    d = dt.date(year + (month == 12), month % 12 + 1, 1)
    return back(d, 1)


def expiry_date(rule, year, month):
    kind, offset = rule["rule"], int(rule.get("offset", 0))
    if kind == "third_wednesday":
        return back(_nth_weekday(year, month, 2, 3), offset)
    if kind == "day_15":
        return back(dt.date(year, month, 15), 1)
    if kind == "month_end":
        return back(last_business_day(year, month), offset)
    if kind == "prior_month_end":
        return back(dt.date(year, month, 1), 1)
    raise ValueError(f"Regla de vencimiento desconocida: {kind}")


def mark(rule, dates):
    """Asocia cada vencimiento con el primer reporte de fecha igual o posterior.

    `dates` son las fechas de reporte en orden ascendente (AAAA-MM-DD).
    Devuelve (vencimientos dentro del histórico, siguiente vencimiento).
    Cada vencimiento es {"d": fecha, "c": contrato (p. ej. "Z26"), "r": fila}.
    """
    if not rule or not dates:
        return [], None
    first, last = dates[0], dates[-1]
    found, upcoming = [], None
    for year in range(int(first[:4]), int(last[:4]) + 3):
        for month in sorted(rule["months"]):
            day = expiry_date(rule, year, month).isoformat()
            item = {"d": day, "c": f"{MONTH_CODES[month - 1]}{year % 100:02d}"}
            if day < first:
                continue
            if day > last:
                upcoming = upcoming if upcoming and upcoming["d"] <= day else item
                continue
            item["r"] = dates[bisect.bisect_left(dates, day)]
            found.append(item)
    found.sort(key=lambda x: x["d"], reverse=True)
    return found, upcoming
