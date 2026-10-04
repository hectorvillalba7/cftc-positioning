"""Transforma las filas de la CFTC en la tabla que se ve en la web.

Por cada activo se genera, para cada grupo de traders, el mismo bloque de
nueve columnas del Excel original:

    tl, ts    nº de traders long / short
    ptl, pts  % de esos traders sobre el total de traders
    pl, ps    posiciones long / short (contratos)
    pt        total (long + short)
    pol, pos  % sobre open interest long / short

más `tt` (total de traders) al principio.
"""

from .schemas import CODE_FIELD, DATE_FIELD, candidates

FIELDS = ["tl", "ts", "ptl", "pts", "pl", "ps", "pt", "pol", "pos"]


def num(value):
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() and "." not in str(value) else f


def resolve_fields(schema, groups, available):
    """Mapea cada columna lógica al nombre real que usa la API.

    Devuelve (mapa, lista de columnas no encontradas).
    """
    missing = []

    def pick(base):
        for name in candidates(base):
            if name in available:
                return name
        missing.append(base)
        return None

    fmap = {"tt": pick(schema["total_traders"])}
    for g in groups:
        spec = schema["groups"][g]
        fmap[g] = {
            "tl": pick(spec["traders"] + "_long"),
            "ts": pick(spec["traders"] + "_short"),
            "pl": pick(spec["positions"] + "_long"),
            "ps": pick(spec["positions"] + "_short"),
            "pol": pick(spec["pct_oi"] + "_long"),
            "pos": pick(spec["pct_oi"] + "_short"),
        }
    return fmap, missing


def _pct(part, total):
    if part is None or not total:
        return None
    return round(part * 100 / total, 2)


def build_asset(rows, codes, fmap, groups, invert, settings):
    """Construye la tabla, los mín/máx y los eventos de un activo."""
    # Si un activo junta varios códigos de contrato, manda el primero de la lista.
    rows = sorted(rows, key=lambda r: codes.index(r[CODE_FIELD]))
    by_date = {}
    for r in rows:
        by_date.setdefault(r[DATE_FIELD][:10], r)
    dates = sorted(by_date)

    columns = ["tt"] + [f"{g}.{f}" for g in groups for f in FIELDS]
    table = []
    for d in dates:
        r = by_date[d]
        get = lambda name: num(r.get(name)) if name else None
        tt = get(fmap["tt"])
        line = [tt]
        for g in groups:
            m = fmap[g]
            tl, ts = get(m["tl"]), get(m["ts"])
            pl, ps = get(m["pl"]), get(m["ps"])
            pol, pos = get(m["pol"]), get(m["pos"])
            if invert:  # el futuro cotiza al revés que el par: largo del futuro = corto del par
                tl, ts, pl, ps, pol, pos = ts, tl, ps, pl, pos, pol
            pt = pl + ps if pl is not None and ps is not None else None
            line += [tl, ts, _pct(tl, tt), _pct(ts, tt), pl, ps, pt, pol, pos]
        table.append(line)

    # Mínimos y máximos de todo el histórico, columna a columna.
    stats = {}
    for i, col in enumerate(columns):
        lo = hi = None
        for d, line in zip(dates, table):
            v = line[i]
            if v is None:
                continue
            if lo is None or v < lo[0]:
                lo = (v, d)
            if hi is None or v > hi[0]:
                hi = (v, d)
        if lo:
            stats[col] = {"min": lo[0], "min_date": lo[1], "max": hi[0], "max_date": hi[1]}

    # Máximo dinámico: se anota cada vez que una columna supera el máximo de
    # todas las semanas anteriores, una vez pasado el periodo de referencia.
    warmup_until = str(settings["warmup_until"])
    min_weeks = int(settings.get("warmup_min_weeks", 104))
    wanted = set(settings["event_fields"])
    events = []
    for i, col in enumerate(columns):
        if col.split(".")[-1] not in wanted:
            continue
        best, seen = None, 0
        for d, line in zip(dates, table):
            v = line[i]
            if v is None:
                continue
            if best is None:
                best = (v, d)
            elif v > best[0]:
                if d >= warmup_until and seen >= min_weeks:
                    events.append({"d": d, "c": col, "v": v, "p": best[0], "pd": best[1]})
                best = (v, d)
            seen += 1
    events.sort(key=lambda e: (e["d"], -columns.index(e["c"])), reverse=True)

    return {
        "columns": columns,
        "dates": dates[::-1],  # la semana más reciente primero, como en el Excel
        "rows": table[::-1],
        "stats": stats,
        "events": events,
    }
