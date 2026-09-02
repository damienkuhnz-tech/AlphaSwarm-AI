# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# (libellé, note obtenue, note max)
criteres = [
    ("Note de recherche", 2, 2),
    ("Allocation", 2, 2),
    ("Génération ordres", 2, 2),
    ("Justesse données", 1.5, 2),
    ("Absence hallucination", 2, 2),
    ("Dégradation gracieuse", 1, 2),
    ("Cohérence inter-agents", 2, 2),
    ("Respect exclusions", 1, 2),
]

total = sum(c[1] for c in criteres)
total_max = sum(c[2] for c in criteres)

VERT = "#2e7d32"
ORANGE = "#f5a409"
GRIS = "#e8e8e8"

def fmt(x):
    return f"{x:g}".replace(".", ",") if x != int(x) else f"{int(x)}"

fig, ax = plt.subplots(figsize=(13.3, 7.5), dpi=200)

labels = [c[0] for c in criteres][::-1]
notes = [c[1] for c in criteres][::-1]
maxis = [c[2] for c in criteres][::-1]

for i, (n, m) in enumerate(zip(notes, maxis)):
    if n < m:
        ax.barh(i, m, height=0.62, color=GRIS, edgecolor="#bbbbbb",
                linewidth=0.8, zorder=2)
    ax.barh(i, n, height=0.62, color=VERT if n == m else ORANGE,
            edgecolor="none", zorder=3)
    ax.text(m + 0.04, i, f"{fmt(n)}/{m}", va="center", ha="left",
            fontweight="bold", fontsize=15)

ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels, fontsize=16)
ax.set_xlim(0, 2.18)
ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0])
ax.set_xticklabels(["0.00", "0.25", "0.50", "0.75", "1.00",
                    "1.25", "1.50", "1.75", "2.00"], fontsize=14)
ax.set_xlabel("Points", fontsize=15)

ax.set_title(
    "Figure 9 Grille de notation récapitulative\n"
    f"Score global : {fmt(total)} / {int(total_max)}",
    fontsize=20, fontweight="bold", pad=16,
)

ax.set_axisbelow(False)
ax.xaxis.grid(True, color="white", linewidth=1.4, zorder=4)
ax.tick_params(axis="y", length=0)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(True)

legende = [
    Patch(facecolor=VERT, label="Pleinement acquis"),
    Patch(facecolor=ORANGE, label="Partiellement acquis"),
]
ax.legend(handles=legende, loc="upper center", bbox_to_anchor=(0.5, -0.13),
          ncol=2, fontsize=14, framealpha=0.95)

fig.tight_layout()
out = r"C:\Users\Kylor\finagent\logs\figures\analyse\I_grille_recap.png"
fig.savefig(out, facecolor="white", bbox_inches="tight")
print(out)
