"""Descarga de liquidaciones del CME: open interest por strike de las opciones
y volumen / open interest de los futuros.

Usa los mismos servicios que las páginas "Settlements" de cmegroup.com:

    /CmeWS/mvc/Settlements/Options/TradeDateAndExpirations/{futuro}
    /CmeWS/mvc/Settlements/Options/Settlements/{opcion}/OOF
    /CmeWS/mvc/Settlements/Futures/Settlements/{futuro}/FUT

Importante: el campo openInterest de una liquidación es el OI al cierre de la
sesión ANTERIOR ("Prior Day OI" en la web). Por eso cada fila guarda la fecha
de negociación (trade_date) y la fecha a la que se refiere el OI (oi_date).
"""

import json
import time
import urllib.parse
import urllib.request

BASE = "https://www.cmegroup.com"
REFERER = BASE + "/markets/fx/g10/euro-fx.settlements.options.html"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": REFERER,
}

try:  # curl_cffi imita la huella TLS de Chrome; el CME bloquea a menudo otros clientes.
    from curl_cffi import requests as _cffi
    _SESSION = _cffi.Session(impersonate="chrome")
except Exception:  # pragma: no cover - sin curl_cffi se usa urllib
    _SESSION = None


# Códigos de las series mensuales (el resto son semanales: lunes a viernes).
MONTHLY = {"EU2", "EUR"}


class Blocked(RuntimeError):
    """El CME ha rechazado la petición (403 / página anti-bots)."""


def _get(path, params=None, retries=4, pause=0.35):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    last = None
    for attempt in range(retries):
        try:
            if _SESSION is not None:
                resp = _SESSION.get(url, headers=HEADERS, timeout=60)
                status, body = resp.status_code, resp.text
            else:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=60) as r:
                    status, body = r.status, r.read().decode("utf-8")
            if status == 403:
                raise Blocked(f"403 en {path}")
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            data = json.loads(body)
            time.sleep(pause)
            return data
        except Blocked:
            raise
        except Exception as exc:
            last = exc
            if "403" in str(exc):
                raise Blocked(str(exc))
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"No se pudo descargar {path}: {last}")


def us_date(iso):
    """2026-10-23 -> 10/23/2026 (formato que pide el CME)."""
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def iso_date(us):
    """10/23/2026 -> 2026-10-23."""
    m, d, y = us.split("/")
    return f"{y}-{int(m):02d}-{int(d):02d}"


def num(value, cast=float):
    """'1,003' -> 1003; '-', 'CAB', '' -> None. Quita sufijos A/B de precios."""
    if value is None:
        return None
    s = str(value).replace(",", "").strip().rstrip("AB")
    if s in ("", "-", "CAB"):
        return None
    try:
        return cast(float(s)) if cast is int else cast(s)
    except ValueError:
        return None


def option_series(future_id):
    """Series de opciones del futuro (mensuales y semanales) con sus vencimientos
    y las fechas de negociación disponibles (las últimas 5 sesiones)."""
    groups = _get(f"/CmeWS/mvc/Settlements/Options/TradeDateAndExpirations/{future_id}")
    out = []
    for g in groups:
        for e in g.get("expirations", []):
            exp = e["expiration"]
            out.append({
                "series": g.get("optionType"),
                "series_label": g.get("label"),
                "weekly": g.get("optionType") not in MONTHLY,
                "product_id": e["productId"],
                "contract": e["contractId"],
                "exp_code": exp["code"],
                "exp_month": f"{exp['year']}-{int(exp['month']):02d}",
                "trade_dates": sorted(iso_date(t["formatedDate"]) for t in e.get("tradeDates", [])),
            })
    return out


def option_settlements(serie, trade_date):
    """Filas (strike, call/put) de una serie para una fecha. Solo las que tienen
    OI o volumen."""
    pid = serie["product_id"]
    data = _get(f"/CmeWS/mvc/Settlements/Options/Settlements/{pid}/OOF", {
        "strategy": "DEFAULT",
        "optionProductId": pid,
        "monthYear": serie["contract"],
        "optionExpiration": f"{pid}-{serie['exp_code']}",
        "tradeDate": us_date(trade_date),
        "pageSize": 1000,
    })
    rows = []
    for s in data.get("settlements", []):
        oi, vol = num(s.get("openInterest"), int), num(s.get("volume"), int)
        if not oi and not vol:
            continue
        rows.append({
            "strike": num(s.get("strike")),
            "cp": "C" if str(s.get("type", "")).lower().startswith("c") else "P",
            "settle": num(s.get("settle")),
            "volume": vol or 0,
            "oi": oi or 0,
        })
    return rows, data.get("reportType")


def future_settlements(future_id, trade_date):
    """Liquidación, volumen y OI (sesión anterior) de cada vencimiento del futuro."""
    data = _get(f"/CmeWS/mvc/Settlements/Futures/Settlements/{future_id}/FUT", {
        "strategy": "DEFAULT",
        "tradeDate": us_date(trade_date),
        "pageSize": 100,
    })
    rows = []
    for s in data.get("settlements", []):
        if str(s.get("month", "")).lower().startswith("total"):
            continue
        rows.append({
            "contract": s.get("month"),
            "settle": num(s.get("settle")),
            "change": num(s.get("change")),
            "volume": num(s.get("volume"), int) or 0,
            "oi": num(s.get("openInterest"), int) or 0,
        })
    return rows, data.get("reportType")
