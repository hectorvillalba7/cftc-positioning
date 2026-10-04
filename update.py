#!/usr/bin/env python3
"""Descarga los reportes de la CFTC, calcula la tabla de cada activo y deja
los datos listos para la web en docs/data/. Si el reporte es nuevo y alguna
columna marca máximo histórico, envía un correo.

    python update.py                 # ejecución normal (la que usa GitHub Actions)
    python update.py --force         # recalcula aunque no haya reporte nuevo
    python update.py --test-email    # envía el resumen del último reporte, para probar Gmail
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

from cot import compute, fetch, notify, schemas

ROOT = Path(__file__).resolve().parent


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def build_report(key, rc, settings, rows, out_dir, expiries=None):
    """Calcula y escribe todos los activos de un reporte. Devuelve su ficha para index.json."""
    schema = schemas.REPORTS[key]
    groups = rc["groups"]
    available = set().union(*(r.keys() for r in rows)) if rows else set()
    fmap, missing = compute.resolve_fields(schema, groups, available)
    if missing:
        print(f"[{key}] AVISO: columnas no encontradas en la API: {', '.join(missing)}")
    if all(fmap[g]["pl"] is None for g in groups):
        raise SystemExit(f"[{key}] La API no devuelve las columnas esperadas. Revisa cot/schemas.py.")

    entry = {
        "key": key,
        "title": schema["title"],
        "subtitle": schema["subtitle"],
        "variant": rc.get("variant", "futures_only"),
        "groups": [{"key": g, "label": schema["groups"][g]["label"]} for g in groups],
        "warmup_until": str(settings["warmup_until"]),
        "assets": [],
    }
    payloads = {}
    for asset in rc["assets"]:
        codes = [str(c) for c in (asset["code"] if isinstance(asset["code"], list) else [asset["code"]])]
        asset_rows = [r for r in rows if r.get(schemas.CODE_FIELD) in codes]
        if not asset_rows:
            raise SystemExit(f"[{key}] Sin datos para {asset['name']} (código {', '.join(codes)}). ¿Es correcto el código?")
        rule = asset.get("expiry") or (expiries or {}).get(asset["id"])
        data = compute.build_asset(asset_rows, codes, fmap, groups, bool(asset.get("invert")), settings, rule)
        data.update({"report": key, "id": asset["id"], "name": asset["name"], "inverted": bool(asset.get("invert"))})
        dump(out_dir / key / f"{asset['id']}.json", data)
        payloads[asset["id"]] = data
        entry["assets"].append({
            "id": asset["id"],
            "name": asset["name"],
            "inverted": bool(asset.get("invert")),
            "latest": data["dates"][0],
            "weeks": len(data["dates"]),
        })
        print(f"[{key}] {asset['name']}: {len(data['dates'])} semanas, {data['dates'][-1]} a {data['dates'][0]}, "
              f"{len(data['events'])} superaciones")

    entry["latest"] = max(a["latest"] for a in entry["assets"])
    for a in entry["assets"]:
        a["latest_events"] = [e for e in payloads[a["id"]]["events"] if e["d"] == entry["latest"]]
    return entry, payloads


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "data"), help="carpeta de salida")
    ap.add_argument("--force", action="store_true", help="recalcular aunque no haya reporte nuevo")
    ap.add_argument("--test-email", action="store_true", help="enviar el resumen del último reporte")
    ap.add_argument("--dry-run-email", metavar="FICHERO", help="guardar el correo en un fichero en vez de enviarlo")
    ap.add_argument("--fixtures", metavar="CARPETA", help="leer <reporte>.json de una carpeta en vez de la API (pruebas)")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    settings, notify_cfg = cfg["settings"], cfg.get("notify") or {}
    out_dir = Path(args.out)
    index_path = out_dir / "index.json"
    prev = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"reports": []}
    prev_reports = {r["key"]: r for r in prev["reports"]}

    reports, email_failed = [], False
    for key, rc in cfg["reports"].items():
        if not rc.get("enabled", True) or not rc.get("assets"):
            continue
        schema = schemas.REPORTS[key]
        dataset = rc.get("dataset") or schema["datasets"][rc.get("variant", "futures_only")]
        expiries = cfg.get("expiries") or {}
        used = {a["id"]: expiries.get(a["id"]) for a in rc["assets"]}
        config_hash = hashlib.sha1(json.dumps([rc, settings, used], sort_keys=True, default=str).encode()).hexdigest()[:12]
        old = prev_reports.get(key)

        # Comprobación barata: si la CFTC no ha publicado nada nuevo, no se descarga el histórico.
        up_to_date = (old and not args.force and not args.fixtures
                      and old.get("config_hash") == config_hash
                      and old.get("notified_through") == old.get("latest"))
        if up_to_date:
            remote = fetch.latest_date(dataset)
            if remote and remote <= old["latest"]:
                print(f"[{key}] sin reporte nuevo (último: {old['latest']})")
                reports.append(old)
                if args.test_email:
                    labels = {g["key"]: g["label"] for g in old["groups"]}
                    items = [(a["name"], e) for a in old["assets"] for e in a["latest_events"]]
                    notify.send(*notify.build_message(old["title"], old["latest"], items, labels, notify_cfg.get("site_url")),
                                dry_run_path=args.dry_run_email)
                continue

        if args.fixtures:
            rows = json.loads((Path(args.fixtures) / f"{key}.json").read_text(encoding="utf-8"))
        else:
            codes = [str(c) for a in rc["assets"] for c in (a["code"] if isinstance(a["code"], list) else [a["code"]])]
            rows = fetch.fetch_rows(dataset, codes)
        # Un reporte puede fijar sus propias reglas de aviso en config.yaml.
        own = {k: rc[k] for k in ("warmup_until", "warmup_min_weeks", "event_fields") if k in rc}
        entry, payloads = build_report(key, rc, {**settings, **own}, rows, out_dir, expiries)
        entry["config_hash"] = config_hash
        labels = {g["key"]: g["label"] for g in entry["groups"]}
        names = {a["id"]: a["name"] for a in entry["assets"]}

        # ¿Qué hay que avisar? Todo lo posterior al último reporte ya avisado.
        # Así un reporte que sale en lunes, o varios acumulados, se avisan igual.
        through = old.get("notified_through") if old else None
        entry["notified_through"] = entry["latest"]
        if args.test_email:
            items = [(a["name"], e) for a in entry["assets"] for e in a["latest_events"]]
            notify.send(*notify.build_message(entry["title"], entry["latest"], items, labels, notify_cfg.get("site_url")),
                        dry_run_path=args.dry_run_email)
        elif through is None:
            print(f"[{key}] primera carga: no se envía correo")
        elif entry["latest"] > through:
            items = sorted(((names[i], e) for i, p in payloads.items() for e in p["events"] if e["d"] > through),
                           key=lambda x: x[1]["d"], reverse=True)
            print(f"[{key}] reporte nuevo ({entry['latest']}): {len(items)} máximos nuevos")
            if items or notify_cfg.get("send_when_no_events"):
                try:
                    notify.send(*notify.build_message(entry["title"], entry["latest"], items, labels, notify_cfg.get("site_url")),
                                dry_run_path=args.dry_run_email)
                except Exception as exc:
                    print(f"[correo] ERROR: {exc}")
                    entry["notified_through"] = through  # se reintenta en la próxima ejecución
                    email_failed = True
        reports.append(entry)

    if not reports:
        raise SystemExit("No hay ningún reporte activado en config.yaml")
    dump(index_path, {
        "latest": max(r["latest"] for r in reports),
        "warmup_until": str(settings["warmup_until"]),
        "event_fields": settings["event_fields"],
        "reports": reports,
    })
    if email_failed:
        sys.exit("Los datos se han actualizado, pero el correo no se pudo enviar.")


if __name__ == "__main__":
    main()
