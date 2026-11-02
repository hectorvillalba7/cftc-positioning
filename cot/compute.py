"""Transforma las filas de la CFTC en la tabla que se ve en la web.

Por cada activo se genera, para cada grupo de traders, el mismo bloque de
nueve columnas del Excel original:

    tl, ts    nº de traders long / short
    ptl, pts  % de esos traders sobre el total de traders
    pl, ps    posiciones long / short (contratos)
    pt        total (long + short)
    pol, pos  % sobre open interest long / short

más `tt` (total de traders) al principio.

En los grupos que tienen activadas las columnas de opciones (`options_groups`
en config.yaml) se añaden cuatro más, que salen de restar el reporte de
solo futuros al de futuros + opciones (combined):

    ol, os    opciones del lado largo / corto, en futuros-equivalentes (delta)
    xl, xs    futuros + opciones: long / short de futuros más su lado de opciones

    lado largo = (Long combined - Long futuros) [+ (Spread combined - Spread futuros)]
    lado corto = (Short combined - Short futuros) [+ (Spread combined - Spread futuros)]

El término del spreading solo se suma en los grupos que lo tienen (Money
Managers sí, PMPU no): al meter las opciones, la CFTC pasa a spreading la
parte en la que cada trader queda igualado entre largo y corto, y sin esa
corrección el lado de opciones saldría falseado.
"""

from . import expiry
from .schemas import CODE_FIELD, DATE_FIELD, find_field

FIELDS = ["tl", "ts", "ptl", "pts", "pl", "ps", "pt", "pol", "pos"]
OPT_FIELDS = ["ol", "os", "xl", "xs"]
DEFAULT_OPT_FIELDS = ["ol", "os"]  # los que se muestran si config.yaml no dice otra cosa


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
        name = find_field(base, available)
        if name is None:
            missing.append(base)
        return name

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


def resolve_option_fields(schema, groups, available_fut, available_comb):
    """Columnas necesarias para el lado de opciones de cada grupo.

    Devuelve (mapa, lista de columnas no encontradas). Un grupo al que le
    falte alguna columna queda con mapa None y sus columnas de opciones
    salen vacías (mejor vacías que mal calculadas).
    """
    missing, out = [], {}
    for g in groups:
        spec = schema["groups"][g]
        bases = {"pl": spec["positions"] + "_long", "ps": spec["positions"] + "_short"}
        if spec.get("spread"):
            bases["sp"] = spec["positions"] + "_spread"
        m, ok = {}, True
        for side, available, tag in (("fut", available_fut, "solo futuros"), ("comb", available_comb, "combined")):
            m[side] = {}
            for k, base in bases.items():
                name = find_field(base, available)
                if name is None:
                    missing.append(f"{base} ({tag})")
                    ok = False
                m[side][k] = name
        m["spread"] = bool(spec.get("spread"))
        out[g] = m if ok else None
    return out, missing


def option_sides(fut, comb, m):
    """[ol, os, xl, xs] de un grupo en una semana, o Nones si falta algún dato."""
    if m is None or fut is None or comb is None:
        return [None] * 4
    f = {k: num(fut.get(n)) for k, n in m["fut"].items()}
    c = {k: num(comb.get(n)) for k, n in m["comb"].items()}
    if any(v is None for v in (*f.values(), *c.values())):
        return [None] * 4
    ol, os_ = c["pl"] - f["pl"], c["ps"] - f["ps"]
    if m["spread"]:
        moved = c["sp"] - f["sp"]
        ol, os_ = ol + moved, os_ + moved
    return [ol, os_, f["pl"] + ol, f["ps"] + os_]


def _pct(part, total):
    if part is None or not total:
        return None
    return round(part * 100 / total, 2)


def _by_date(rows, codes):
    # Si un activo junta varios códigos de contrato, manda el primero de la lista.
    by_date = {}
    for r in sorted(rows, key=lambda r: codes.index(r[CODE_FIELD])):
        by_date.setdefault(r[DATE_FIELD][:10], r)
    return by_date


def build_asset(rows, codes, fmap, groups, invert, settings, expiry_rule=None, options=None):
    """Construye la tabla, los mín/máx y los eventos de un activo.

    `options`, si se pasa, es {"rows": filas del combined, "fmap": mapa de
    resolve_option_fields, "fields": columnas de opciones a mostrar}; añade
    esas columnas a los grupos del mapa.
    """
    by_date = _by_date(rows, codes)
    dates = sorted(by_date)
    opt_map = (options or {}).get("fmap") or {}
    comb_by_date = _by_date((options or {}).get("rows") or [], codes)
    wanted = (options or {}).get("fields") or DEFAULT_OPT_FIELDS
    opt_fields = [f for f in OPT_FIELDS if f in wanted]

    columns = ["tt"] + [f"{g}.{f}" for g in groups for f in FIELDS + (opt_fields if g in opt_map else [])]
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
            if g in opt_map:
                ol, os_, xl, xs = option_sides(r, comb_by_date.get(d), opt_map[g])
                if invert:
                    ol, os_, xl, xs = os_, ol, xs, xl
                values = {"ol": ol, "os": os_, "xl": xl, "xs": xs}
                line += [values[f] for f in opt_fields]
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

    # Vencimientos de contrato, cada uno en el primer reporte posterior.
    expiries, next_expiry = expiry.mark(expiry_rule, dates)

    return {
        "columns": columns,
        "dates": dates[::-1],  # la semana más reciente primero, como en el Excel
        "rows": table[::-1],
        "stats": stats,
        "events": events,
        "expiries": expiries,
        "next_expiry": next_expiry,
    }
