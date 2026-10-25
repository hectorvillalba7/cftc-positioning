#!/usr/bin/env python3
"""Guarda cada día el open interest por strike de las opciones de divisas del
CME (mensuales y semanales) y el volumen / OI de los futuros.

El CME solo publica las últimas 5 sesiones, así que el histórico se construye
guardando cada día. Cada ejecución descarga las sesiones que falten, de modo
que si un día no se ejecuta, la siguiente lo recupera (hasta 5 sesiones atrás).

    python cme_oi.py                       # todas las divisas de config.yaml
    python cme_oi.py --assets eurusd       # solo algunas
    python cme_oi.py --dates 2026-10-23    # forzar fechas concretas (las vuelve a escribir)

Ficheros (en data/cme/<activo>/):
    options/AAAA-MM-DD.csv.gz   una fila por serie, vencimiento, strike y call/put
    futures.csv                 una fila por sesión y vencimiento del futuro

Columnas: trade_date = sesión de la liquidación (volumen y precio);
oi_date = sesión a la que corresponde el open interest (la anterior).
"""

import argparse
import csv
import gzip
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from cot import cme

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "cme"
OPT_COLS = ["trade_date", "oi_date", "series", "series_label", "contract", "exp_month",
            "strike", "cp", "settle", "volume", "oi"]
FUT_COLS = ["trade_date", "oi_date", "contract", "settle", "change", "volume", "oi"]


def prev_session(d, known):
    """Sesión anterior a d: la última fecha conocida anterior, o el día hábil previo."""
    earlier = [k for k in known if k < d]
    if earlier:
        return max(earlier)
    x = date.fromisoformat(d) - timedelta(days=1)
    while x.weekday() >= 5:
        x -= timedelta(days=1)
    return x.isoformat()


def stored_dates(asset_dir):
    return {p.name[:10] for p in (asset_dir / "options").glob("*.csv.gz")}


def write_options(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=OPT_COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    # mtime=0: el mismo contenido produce el mismo fichero (sin commits vacíos)
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))


def merge_futures(path, new_rows):
    rows = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows[(r["trade_date"], r["contract"])] = r
    for r in new_rows:
        rows[(r["trade_date"], r["contract"])] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FUT_COLS, lineterminator="\n")
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in FUT_COLS})


def run_asset(asset, cfg, force_dates):
    aid, fid = asset["id"], asset["future_id"]
    adir = OUT / aid
    series = cme.option_series(fid)
    max_monthly = cfg.get("monthly_expirations", 6)
    monthly = [s for s in series if not s["weekly"]][:max_monthly]
    weekly = [s for s in series if s["weekly"]] if cfg.get("weeklies", True) else []
    chosen = monthly + weekly

    available = sorted(set().union(*(s["trade_dates"] for s in series))) if series else []
    have = stored_dates(adir)
    todo = force_dates or [d for d in available if d not in have]
    if not todo:
        print(f"[{aid}] al día ({len(have)} sesiones guardadas)")
        return 0

    known = sorted(set(available) | have)
    saved = 0
    for d in todo:
        oi_date = prev_session(d, known)
        rows, preliminary = [], False
        for s in chosen:
            if s["trade_dates"] and d not in s["trade_dates"]:
                continue
            got, rtype = cme.option_settlements(s, d)
            if rtype and rtype.lower().startswith("prelim"):
                preliminary = True
            for r in got:
                rows.append({"trade_date": d, "oi_date": oi_date, "series": s["series"],
                             "series_label": s["series_label"], "contract": s["contract"],
                             "exp_month": s["exp_month"], **r})
        if preliminary and not force_dates:
            print(f"[{aid}] {d}: liquidación todavía preliminar, se guardará en la próxima ejecución")
            continue
        if not rows:
            print(f"[{aid}] {d}: sin datos")
            continue
        rows.sort(key=lambda r: (r["exp_month"], r["series"], r["contract"], r["strike"], r["cp"]))
        write_options(adir / "options" / f"{d}.csv.gz", rows)

        fut, _ = cme.future_settlements(fid, d)
        merge_futures(adir / "futures.csv",
                      [{"trade_date": d, "oi_date": oi_date, **r} for r in fut])
        total_oi = sum(r["oi"] for r in rows)
        print(f"[{aid}] {d}: {len(rows)} filas de opciones (OI total {total_oi:,}), {len(fut)} futuros")
        saved += 1
    return saved


def write_index(assets):
    index = {"assets": []}
    for a in assets:
        dates = sorted(stored_dates(OUT / a["id"]))
        index["assets"].append({"id": a["id"], "name": a["name"], "future": a["globex"],
                                "first": dates[0] if dates else None,
                                "last": dates[-1] if dates else None, "sessions": len(dates)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", help="ids separados por comas (por defecto, todos)")
    ap.add_argument("--dates", help="fechas AAAA-MM-DD separadas por comas")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")).get("cme_oi", {})
    if not cfg.get("enabled", False):
        print("cme_oi desactivado en config.yaml")
        return 0
    assets = cfg["assets"]
    if args.assets:
        wanted = set(args.assets.split(","))
        assets = [a for a in assets if a["id"] in wanted]
    force = args.dates.split(",") if args.dates else None

    ok, blocked, failed = 0, [], []
    for a in assets:
        try:
            run_asset(a, cfg, force)
            ok += 1
        except cme.Blocked as exc:
            blocked.append(a["id"])
            print(f"[{a['id']}] BLOQUEADO por el CME: {exc}")
        except Exception as exc:
            failed.append(a["id"])
            print(f"[{a['id']}] ERROR: {exc}")
    write_index(cfg["assets"])

    if ok == 0:
        if blocked:
            print("\nEl CME ha rechazado todas las peticiones desde esta máquina. "
                  "Ejecuta el script en tu ordenador (ver README, sección 'Open interest del CME').")
        return 1
    if failed or blocked:
        print(f"\nCon problemas: {', '.join(failed + blocked)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
