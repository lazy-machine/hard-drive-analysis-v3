"""Figuras 2 a 4 do relatório, em português, a partir dos artefatos da execução completa.

Uso, na raiz do repositório:  python3 article/figures/figuras.py

Lê apenas results/full-2026-11-11/ (metrics.json, detection.csv, calibration.csv) e grava
os arquivos SVG nesta pasta. Não recalcula nenhuma métrica.
"""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

RAIZ = Path(__file__).resolve().parents[2]
RUN = RAIZ / "results" / "full-2026-11-11"
SAIDA = Path(__file__).resolve().parent

TEXTO, TEXTO_2, GRADE = "#0b0b0b", "#52514e", "#e4e3df"
# Uma cor e um marcador por modelo, iguais em todas as figuras.
MODELOS = {
    "hazard_smart": ("SMART + contexto", "#2a78d6", "o"),
    "rule_counters": ("Regra dos contadores críticos", "#eb6834", "s"),
    "hazard_nocritical": ("Sem contadores críticos", "#1baf7a", "^"),
    "hazard_nosmart": ("Sem SMART", "#eda100", "D"),
}
HORIZONTES = [7, 30, 90, 180, 365]
# Horizonte é uma grandeza ordenada: um só matiz, do claro ao escuro, e um marcador por
# horizonte, para que as curvas se distingam também sem cor.
AZUIS = {7: "#86b6ef", 30: "#5598e7", 90: "#2a78d6", 180: "#184f95", 365: "#0d366b"}
MARCAS = {7: "o", 30: "s", 90: "^", 180: "D", 365: "v"}

plt.rcParams.update({
    "font.family": ["Liberation Sans", "DejaVu Sans"],
    "font.size": 9,
    "svg.fonttype": "none",
    "axes.edgecolor": TEXTO_2,
    "axes.labelcolor": TEXTO,
    "axes.linewidth": 0.8,
    "xtick.color": TEXTO_2,
    "ytick.color": TEXTO_2,
    "text.color": TEXTO,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
})


def virgula(valor: float, casas: int) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def porcento(valor: float, _pos=None) -> str:
    """Rótulo de eixo em porcentagem, com vírgula decimal e sem zeros à direita."""
    texto = f"{100 * valor:.3f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + "%"


def gravar(fig, nome: str) -> None:
    caminho = SAIDA / nome
    fig.savefig(caminho, format="svg", metadata={"Date": None})
    # Arial é a fonte do relatório; Liberation Sans tem as mesmas medidas.
    svg = caminho.read_text(encoding="utf-8").replace(
        "'Liberation Sans'", "Arial, 'Liberation Sans', Helvetica, sans-serif")
    caminho.write_text(svg, encoding="utf-8")
    # Cópia em PNG para a versão Word do relatório (article/docx/build_docx.py).
    fig.savefig(caminho.with_suffix(".png"), format="png", dpi=200, metadata={"Software": None})
    plt.close(fig)


def figura_roc_auc(metricas: dict) -> None:
    # Estimador de acompanhamento completo, o mesmo da Tabela 2.
    linhas = {(r["model"], r["horizon"]): r for r in metricas["full_follow_up"]}
    fig, ax = plt.subplots(figsize=(6.3, 3.7), layout="constrained")
    desloc = {"hazard_smart": -0.24, "rule_counters": -0.08,
              "hazard_nocritical": 0.08, "hazard_nosmart": 0.24}
    for modelo, (rotulo, cor, marcador) in MODELOS.items():
        xs = [i + desloc[modelo] for i in range(len(HORIZONTES))]
        ys = [linhas[modelo, h]["auc"] for h in HORIZONTES]
        ics = [linhas[modelo, h]["auc_ci"] for h in HORIZONTES]
        erro = [[y - ic[0] for y, ic in zip(ys, ics, strict=True)],
                [ic[1] - y for y, ic in zip(ys, ics, strict=True)]]
        ax.errorbar(xs, ys, yerr=erro, fmt=marcador, color=cor, markersize=5.5,
                    markeredgecolor="white", markeredgewidth=0.6, elinewidth=1.2,
                    capsize=2.5, label=rotulo)
    ax.axhline(0.5, color=TEXTO_2, linewidth=0.8, linestyle=(0, (4, 3)))
    ax.text(len(HORIZONTES) - 0.52, 0.507, "ordenação aleatória", ha="right",
            va="bottom", color=TEXTO_2, fontsize=8)
    ax.set_xticks(range(len(HORIZONTES)), [f"{h} dias" for h in HORIZONTES])
    ax.set_xlim(-0.5, len(HORIZONTES) - 0.5)
    ax.set_ylim(0.45, 0.95)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: virgula(v, 1)))
    ax.set_xlabel("Horizonte de previsão (falha em até)")
    ax.set_ylabel("ROC-AUC")
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    fig.legend(loc="outside upper center", ncols=2, handletextpad=0.3, columnspacing=1.6)
    gravar(fig, "figura-2-roc-auc.svg")


def figura_alertas() -> None:
    with open(RUN / "detection.csv", newline="", encoding="utf-8") as f:
        registros = list(csv.DictReader(f))
    fig, ax = plt.subplots(figsize=(6.3, 3.5), layout="constrained")
    faixas = None
    for modelo in ("hazard_smart", "rule_counters", "hazard_nosmart"):
        rotulo, cor, marcador = MODELOS[modelo]
        dados = sorted((r for r in registros if r["model"] == modelo),
                       key=lambda r: int(r["lo"]))
        faixas = [r["days_before_failure"].replace("-", " a ") for r in dados]
        ys = [100 * float(r["alerted"]) for r in dados]
        ax.plot(range(len(ys)), ys, color=cor, marker=marcador, linewidth=2,
                markersize=6, markeredgecolor="white", markeredgewidth=0.8, label=rotulo)
        # Valores nas pontas; o da regra fica abaixo do ponto final para não colidir.
        abaixo = modelo == "rule_counters"
        ax.annotate(virgula(ys[0], 0) + "%", (0, ys[0]), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=8, color=TEXTO)
        ax.annotate(virgula(ys[-1], 0) + "%", (len(ys) - 1, ys[-1]),
                    xytext=(0, -13 if abaixo else 7), textcoords="offset points",
                    ha="center", fontsize=8, color=TEXTO)
    ax.set_xticks(range(len(faixas)), faixas)
    ax.set_ylim(0, 80)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("Dias até a falha (faixas de largura desigual)")
    ax.set_ylabel("Retratos com alerta")
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    fig.legend(loc="outside upper center", ncols=3, handletextpad=0.4, columnspacing=1.6)
    gravar(fig, "figura-3-alertas.svg")


def figura_calibracao() -> None:
    with open(RUN / "calibration.csv", newline="", encoding="utf-8") as f:
        registros = [r for r in csv.DictReader(f) if r["model"] == "hazard_smart"]
    fig, ax = plt.subplots(figsize=(5.2, 4.6), layout="constrained")
    limites = (2e-5, 0.3)
    ax.plot(limites, limites, color=TEXTO_2, linewidth=0.8, linestyle=(0, (4, 3)))
    ax.text(0.19, 0.25, "calibração perfeita", rotation=45, rotation_mode="anchor",
            ha="right", va="bottom", color=TEXTO_2, fontsize=8)
    for h in HORIZONTES:
        dados = sorted((r for r in registros if int(r["horizon"]) == h),
                       key=lambda r: int(r["group"]))
        xs = [float(r["predicted"]) for r in dados]
        ys = [float(r["observed_km"]) for r in dados]
        ax.plot(xs, ys, color=AZUIS[h], marker=MARCAS[h], linewidth=1.6, markersize=5,
                markeredgecolor="white", markeredgewidth=0.6, label=f"{h} dias")
        # Rótulo direto no decil de menor risco, onde as curvas não se sobrepõem.
        ax.annotate(f"{h} dias", (xs[0], ys[0]), xytext=(-5, 5),
                    textcoords="offset points", ha="right", va="bottom", fontsize=8,
                    color=TEXTO)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(*limites)
    ax.set_ylim(*limites)
    marcas = [1e-4, 1e-3, 1e-2, 1e-1]
    for eixo in (ax.xaxis, ax.yaxis):
        eixo.set_major_locator(FixedLocator(marcas))
        eixo.set_major_formatter(FuncFormatter(porcento))
        eixo.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Probabilidade prevista de falha no horizonte")
    ax.set_ylabel("Proporção observada (Kaplan-Meier)")
    ax.grid(which="major", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(which="both", length=0)
    ax.set_aspect("equal")
    ax.legend(title="Horizonte", loc="lower right", handletextpad=0.4)
    gravar(fig, "figura-4-calibracao.svg")


def main() -> None:
    metricas = json.loads((RUN / "metrics.json").read_text(encoding="utf-8"))
    figura_roc_auc(metricas)
    figura_alertas()
    figura_calibracao()


if __name__ == "__main__":
    main()
