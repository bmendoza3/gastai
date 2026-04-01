# src/reports/charts.py
from __future__ import annotations

from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # sin GUI, para servidor
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from src.db.storage import get_spend_by_category, get_spend_by_month

# ── Paletas de colores ────────────────────────────────────────────────────────
# Cambia ACTIVE_PALETTE para cambiar el look de todos los gráficos.
# Opciones: "indigo" | "sunset" | "forest" | "ocean"

ACTIVE_PALETTE = "indigo"

PALETTES = {
    # Azules y violetas — look profesional/financiero
    "indigo": [
        "#4F6EF7", "#7B93F9", "#A5B8FB",
        "#6C3FC5", "#9B6FE8", "#C4A7F5",
        "#2EC4B6", "#3DD9C5", "#8EEADE",
        "#F77F4F", "#F9A87B", "#FBC9A5",
        "#E84393", "#F27ABB",
    ],
    # Naranjas, rosas y rojos cálidos — energético
    "sunset": [
        "#FF6B6B", "#FF8E53", "#FFA94D",
        "#FFD166", "#F9C74F", "#EF476F",
        "#F15BB5", "#C77DFF", "#9D4EDD",
        "#06D6A0", "#1B9AAA", "#4CC9F0",
        "#80B918", "#AACC00",
    ],
    # Verdes y tierra — natural/sustentable
    "forest": [
        "#2D6A4F", "#40916C", "#52B788",
        "#74C69D", "#95D5B2", "#B7E4C7",
        "#D4A017", "#E9C46A", "#F4A261",
        "#E76F51", "#7B2D8B", "#9B5DE5",
        "#606C38", "#283618",
    ],
    # Azul verdoso — limpio/minimalista
    "ocean": [
        "#0077B6", "#0096C7", "#00B4D8",
        "#48CAE4", "#90E0EF", "#023E8A",
        "#7B2FBE", "#9D4EDD", "#C77DFF",
        "#FF6B6B", "#FF9F1C", "#2EC4B6",
        "#CBEF43", "#3A86FF",
    ],
}

# Mapeo semántico: qué índice de la paleta usa cada categoría conocida
_CATEGORY_PALETTE_IDX = {
    "transporte":      0,
    "comida":          3,
    "supermercado":    6,
    "salud":           9,
    "entretenimiento": 1,
    "suscripciones":   7,
    "ropa":           10,
    "educacion":       4,
    "hogar":           8,
    "trabajo":         2,
    "viajes":         11,
    "otros":          12,
    "sin categoría":  13,
}


def _category_color(category: str, palette_name: str = ACTIVE_PALETTE) -> str:
    """Retorna color de la paleta indicada para cualquier categoría."""
    palette = PALETTES.get(palette_name, PALETTES[ACTIVE_PALETTE])
    if category in _CATEGORY_PALETTE_IDX:
        idx = _CATEGORY_PALETTE_IDX[category] % len(palette)
    else:
        idx = abs(hash(category)) % len(palette)
    return palette[idx]


CATEGORY_LABELS = {
    "transporte":     "Transporte",
    "comida":         "Comida",
    "supermercado":   "Supermercado",
    "salud":          "Salud",
    "entretenimiento":"Entretención",
    "suscripciones":  "Suscripciones",
    "ropa":           "Ropa",
    "educacion":      "Educación",
    "hogar":          "Hogar",
    "trabajo":        "Trabajo",
    "viajes":         "Viajes",
    "otros":          "Otros",
    "sin categoría":  "Sin categoría",
}


MONTH_NAMES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}


def _fmt_clp(value: float) -> str:
    return f"${value:,.0f}".replace(",", ".")


def _period_label(days_back: int, month: Optional[int], year: Optional[int]) -> str:
    if month and year:
        return f"{MONTH_NAMES_ES.get(month, str(month))} {year}"
    if days_back <= 0:
        return "todos los gastos"
    if days_back == 30:
        return "último mes"
    return f"últimos {days_back} días"


def spend_pie_chart(user_phone: Optional[str] = None, days_back: int = 7,
                    month: Optional[int] = None, year: Optional[int] = None,
                    palette: str = ACTIVE_PALETTE) -> BytesIO:
    """Gráfico de torta: gasto por categoría. Retorna PNG en BytesIO."""
    df = get_spend_by_category(user_phone=user_phone, days_back=days_back, month=month, year=year)

    if df.empty:
        return _empty_chart("Sin gastos en el período seleccionado")

    labels = [CATEGORY_LABELS.get(c, c.replace("_", " ").title()) for c in df["category"]]
    sizes = df["spent_clp"].tolist()
    colors = [_category_color(c, palette) for c in df["category"]]
    total = sum(sizes)

    fig, ax = plt.subplots(figsize=(7, 5.5), facecolor="#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    wedges, _ = ax.pie(
        sizes,
        colors=colors,
        startangle=140,
        wedgeprops={"linewidth": 2, "edgecolor": "white"},
    )

    # Leyenda con montos
    legend_labels = [
        f"{label}  {_fmt_clp(size)}  ({size/total*100:.0f}%)"
        for label, size in zip(labels, sizes)
    ]
    patches = [
        mpatches.Patch(color=c, label=l)
        for c, l in zip(colors, legend_labels)
    ]
    ax.legend(handles=patches, loc="center left", bbox_to_anchor=(1, 0.5),
              fontsize=8.5, frameon=False)

    period = _period_label(days_back, month, year)
    ax.set_title(f"Gastos — {period}\nTotal: {_fmt_clp(total)}",
                 fontsize=12, fontweight="bold", pad=14, color="#2C3E50")

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def spend_bar_chart(user_phone: Optional[str] = None, days_back: int = 7,
                    month: Optional[int] = None, year: Optional[int] = None,
                    palette: str = ACTIVE_PALETTE) -> BytesIO:
    """Gráfico de barras horizontales: gasto por categoría ordenado."""
    df = get_spend_by_category(user_phone=user_phone, days_back=days_back, month=month, year=year)

    if df.empty:
        return _empty_chart("Sin gastos en el período seleccionado")

    df = df.sort_values("spent_clp")
    labels = [CATEGORY_LABELS.get(c, c.replace("_", " ").title()) for c in df["category"]]
    sizes = df["spent_clp"].tolist()
    colors = [_category_color(c, palette) for c in df["category"]]
    total = sum(sizes)

    fig, ax = plt.subplots(figsize=(7, max(3, len(labels) * 0.6 + 1.5)),
                           facecolor="white")
    ax.set_facecolor("white")

    bars = ax.barh(labels, sizes, color=colors, height=0.6, edgecolor="white", linewidth=1.5)

    # Etiquetas de monto al lado de cada barra
    for bar, size in zip(bars, sizes):
        ax.text(bar.get_width() + total * 0.01, bar.get_y() + bar.get_height() / 2,
                _fmt_clp(size), va="center", ha="left", fontsize=8.5, color="#2C3E50")

    ax.set_xlabel("")
    ax.set_xlim(0, max(sizes) * 1.25)
    ax.xaxis.set_visible(False)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.spines["left"].set_color("#DEE2E6")

    period = _period_label(days_back, month, year)
    ax.set_title(f"Gastos — {period}\nTotal: {_fmt_clp(total)}",
                 fontsize=12, fontweight="bold", pad=12, color="#2C3E50")

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def spend_monthly_chart(user_phone: Optional[str] = None) -> BytesIO:
    """Gráfico de barras: gasto total por mes (últimos 12 meses con datos)."""
    df = get_spend_by_month(user_phone=user_phone)

    if df.empty:
        return _empty_chart("Sin gastos registrados")

    df = df.tail(12)
    labels = [f"{MONTH_NAMES_ES[p.month]} {str(p.year)[2:]}" for p in df["month"]]
    sizes = df["spent_clp"].tolist()
    total = sum(sizes)

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.8 + 1.5), 4.5), facecolor="white")
    ax.set_facecolor("white")

    bars = ax.bar(labels, sizes, color="#4A90D9", edgecolor="white", linewidth=1.5, width=0.6)

    for bar, size in zip(bars, sizes):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + total * 0.01,
                _fmt_clp(size), ha="center", va="bottom", fontsize=8, color="#2C3E50")

    ax.set_ylim(0, max(sizes) * 1.2)
    ax.yaxis.set_visible(False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#DEE2E6")
    ax.tick_params(axis="x", labelsize=9, colors="#2C3E50")

    ax.set_title(
        f"Gastos por mes\nTotal período: {_fmt_clp(total)}",
        fontsize=12, fontweight="bold", pad=12, color="#2C3E50"
    )

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _empty_chart(message: str) -> BytesIO:
    fig, ax = plt.subplots(figsize=(5, 3), facecolor="#F8F9FA")
    ax.text(0.5, 0.5, message, ha="center", va="center",
            fontsize=12, color="#95A5A6", transform=ax.transAxes)
    ax.axis("off")
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
