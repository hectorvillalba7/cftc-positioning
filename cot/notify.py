"""Aviso por correo (Gmail) cuando un reporte nuevo trae máximos históricos."""

import os
import smtplib
from email.message import EmailMessage
from html import escape

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
FIELD_LABELS = {
    "tt": "Total de traders",
    "tl": "traders long",
    "ts": "traders short",
    "pl": "posiciones long",
    "ps": "posiciones short",
    "pt": "posiciones totales",
}


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{d}-{MONTHS[int(m) - 1]}-{y[2:]}"


def fmt_num(v):
    return f"{v:,.0f}".replace(",", ".")


def column_label(col, group_labels):
    if "." not in col:
        return FIELD_LABELS[col]
    group, field = col.split(".")
    return f"{group_labels[group]}, {FIELD_LABELS[field]}"


def build_message(report_title, latest, items, group_labels, site_url):
    """items: lista de (nombre del activo, evento)."""
    n = len(items)
    assets = list(dict.fromkeys(name for name, _ in items))
    if n:
        subject = f"CFTC {report_title} {fmt_date(latest)}: {n} nuevo{'s' if n > 1 else ''} máximo{'s' if n > 1 else ''} ({', '.join(assets)})"
    else:
        subject = f"CFTC {report_title} {fmt_date(latest)}: sin nuevos máximos"

    text = [f"Reporte {report_title} con datos al {fmt_date(latest)}.", ""]
    html = [f"<p>Reporte <b>{escape(report_title)}</b> con datos al {fmt_date(latest)}.</p>"]
    if n:
        html.append('<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px">'
                    '<tr style="background:#eef1f4;text-align:left"><th>Fecha</th><th>Activo</th><th>Columna</th>'
                    '<th align="right">Nuevo máximo</th><th align="right">Máximo anterior</th></tr>')
        for name, e in items:
            label = column_label(e["c"], group_labels)
            text.append(f"{fmt_date(e['d'])}  {name}  {label}: {fmt_num(e['v'])} "
                        f"(anterior {fmt_num(e['p'])} del {fmt_date(e['pd'])})")
            html.append(f'<tr style="border-top:1px solid #d5dbe2"><td>{fmt_date(e["d"])}</td><td><b>{escape(name)}</b></td>'
                        f'<td>{escape(label)}</td><td align="right"><b>{fmt_num(e["v"])}</b></td>'
                        f'<td align="right">{fmt_num(e["p"])} ({fmt_date(e["pd"])})</td></tr>')
        html.append("</table>")
    else:
        text.append("Ninguna columna de traders ni de posiciones ha superado su máximo histórico.")
        html.append("<p>Ninguna columna de traders ni de posiciones ha superado su máximo histórico.</p>")
    if site_url:
        text += ["", site_url]
        html.append(f'<p><a href="{escape(site_url)}">Abrir la web</a></p>')
    return subject, "\n".join(text), "\n".join(html)


def send(subject, text, html, dry_run_path=None):
    """Envía el correo. Devuelve True si se envió y None si no hay credenciales.

    Lanza una excepción si Gmail rechaza el envío, para reintentarlo en la
    siguiente ejecución.
    """
    if dry_run_path:
        with open(dry_run_path, "w", encoding="utf-8") as fh:
            fh.write(f"<!-- {subject} -->\n{html}\n")
        print(f"[correo] simulado en {dry_run_path}: {subject}")
        return True
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        print("[correo] sin GMAIL_USER / GMAIL_APP_PASSWORD: no se envía nada")
        return None
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = os.environ.get("MAIL_TO") or user
    msg.set_content(text)
    msg.add_alternative(f"<html><body>{html}</body></html>", subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(user, password.replace(" ", ""))
        smtp.send_message(msg)
    print(f"[correo] enviado a {msg['To']}: {subject}")
    return True
