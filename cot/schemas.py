"""Definición de los reportes de la CFTC que sabe leer el proyecto.

Cada reporte tiene dos datasets en la API pública de la CFTC (solo futuros /
futuros + opciones) y una lista de grupos de traders. Para cada grupo se
indica el prefijo de sus tres familias de columnas: número de traders,
posiciones (contratos) y % sobre open interest.

Los nombres de columna de la API no son del todo consistentes (unas acaban
en "_all" y otras no), así que aquí se guardan sin sufijo y `candidates`
genera las variantes. `update.py` avisa si alguna no aparece.
"""

API = "https://publicreporting.cftc.gov/resource/{dataset}.json"
DATE_FIELD = "report_date_as_yyyy_mm_dd"
CODE_FIELD = "cftc_contract_market_code"


def _group(label, traders, positions, pct_oi):
    return {"label": label, "traders": traders, "positions": positions, "pct_oi": pct_oi}


REPORTS = {
    "tff": {
        "title": "TFF",
        "subtitle": "Traders in Financial Futures",
        "datasets": {"futures_only": "gpe5-46if", "combined": "yw9f-hn96"},
        "total_traders": "traders_tot",
        "groups": {
            "asset_mgr": _group("Asset Managers", "traders_asset_mgr", "asset_mgr_positions", "pct_of_oi_asset_mgr"),
            "dealer": _group("Dealers", "traders_dealer", "dealer_positions", "pct_of_oi_dealer"),
            "lev_money": _group("Leveraged Funds", "traders_lev_money", "lev_money_positions", "pct_of_oi_lev_money"),
            "other_rept": _group("Other Reportables", "traders_other_rept", "other_rept_positions", "pct_of_oi_other_rept"),
        },
    },
    "legacy": {
        "title": "Legacy",
        "subtitle": "Commitments of Traders, formato clásico",
        "datasets": {"futures_only": "6dca-aqww", "combined": "jun7-fc8e"},
        "total_traders": "traders_tot",
        "groups": {
            "noncomm": _group("Non-Commercial", "traders_noncomm", "noncomm_positions", "pct_of_oi_noncomm"),
            "comm": _group("Commercial", "traders_comm", "comm_positions", "pct_of_oi_comm"),
        },
    },
    "disaggregated": {
        "title": "Disaggregated",
        "subtitle": "Commitments of Traders desagregado (commodities)",
        "datasets": {"futures_only": "72hh-3qpy", "combined": "kh3c-gbw2"},
        "total_traders": "traders_tot",
        "groups": {
            "prod_merc": _group("Producer/Merchant", "traders_prod_merc", "prod_merc_positions", "pct_of_oi_prod_merc"),
            "swap": _group("Swap Dealers", "traders_swap", "swap_positions", "pct_of_oi_swap"),
            "m_money": _group("Managed Money", "traders_m_money", "m_money_positions", "pct_of_oi_m_money"),
            "other_rept": _group("Other Reportables", "traders_other_rept", "other_rept_positions", "pct_of_oi_other_rept"),
        },
    },
}

# Columnas cuyo nombre en la API no sigue la regla general.
ALIASES = {
    "swap_positions_short": ["swap__positions_short_all", "swap__positions_short"],
}


def candidates(base):
    """Posibles nombres en la API para una columna dada sin sufijo."""
    return ALIASES.get(base, []) + [base, base + "_all"]
