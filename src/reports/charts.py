# src/reports/charts.py
from __future__ import annotations

from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # sin GUI, para servidor
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from src.db.storage import get_spend_by_category, get_spend_by_month

# Paleta de colores por categoría
CATEGORY_COLORS = {
    "transporte":     "#4A90D9",
    "comida":         "#E8845A",
    "supermercado":   "#5CB85C",
    "salud":          "#D9534F",
    "entretenimiento":"#9B59B6",
    "suscripciones":  "#1ABC9C",
    "ropa":           "#F39C12",
    "educacion":      "#2980B9",
    "hogar":          "#795548",
    "trabajo":        "#607D8B",
    "viajes":         "#E91E63",
    "otros":          "#95A5A6",
    "sin categoría":  "#BDC3C7",
}

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
                    month: Optional[int] = None, year: Optional[int] = None) -> BytesIO:
    """Gráfico de torta: gasto por categoría. Retorna PNG en BytesIO."""
    df = get_spend_by_category(user_phone=user_phone, days_back=days_back, month=month, year=year)

    if df.empty:
        return _empty_chart("Sin gastos en el período seleccionado")

    labels = [CATEGORY_LABELS.get(c, c.title()) for c in df["category"]]
    sizes = df["spent_clp"].tolist()
    colors = [CATEGORY_COLORS.get(c, "#95A5A6") for c in df["category"]]
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
                    month: Optional[int] = None, year: Optional[int] = None) -> BytesIO:
    """Gráfico de barras horizontales: gasto por categoría ordenado."""
    df = get_spend_by_category(user_phone=user_phone, days_back=days_back, month=month, year=year)

    if df.empty:
        return _empty_chart("Sin gastos en el período seleccionado")

    df = df.sort_values("spent_clp")
    labels = [CATEGORY_LABELS.get(c, c.title()) for c in df["category"]]
    sizes = df["spent_clp"].tolist()
    colors = [CATEGORY_COLORS.get(c, "#95A5A6") for c in df["category"]]
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
