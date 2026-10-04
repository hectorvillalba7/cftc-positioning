"""Descarga de datos desde la API pública (Socrata) de la CFTC."""

import json
import os
import time
import urllib.parse
import urllib.request

from .schemas import API, CODE_FIELD, DATE_FIELD

PAGE = 20000


def _get(url, retries=4):
    headers = {"User-Agent": "cftc-posicionamiento/1.0", "Accept": "application/json"}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # red, 5xx, JSON cortado...
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {last}")


def _url(dataset, **params):
    return API.format(dataset=dataset) + "?" + urllib.parse.urlencode(params)


def latest_date(dataset):
    """Fecha (AAAA-MM-DD) del último reporte publicado en el dataset, o None."""
    try:
        data = _get(_url(dataset, **{"$select": f"max({DATE_FIELD}) as d"}), retries=2)
        return data[0]["d"][:10]
    except Exception:
        return None


def fetch_rows(dataset, codes):
    """Todo el histórico de los contratos indicados."""
    where = f"{CODE_FIELD} in(" + ",".join(f"'{c}'" for c in sorted(set(codes))) + ")"
    rows, offset = [], 0
    while True:
        page = _get(_url(dataset, **{
            "$where": where,
            "$order": f"{DATE_FIELD},{CODE_FIELD}",
            "$limit": PAGE,
            "$offset": offset,
        }))
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE
