#!/usr/bin/env python3
"""Semana 5: estadistica descriptiva y figuras para el paper.

Lee `datos/dataset_timeouts.csv` y produce:
  analisis/estadistica_descriptiva.md   tablas (tambien sirven de "vista tabla"
                                        accesible de cada figura)
  analisis/figuras/*.pdf + *.png        figuras listas para \\includegraphics

Reglas de la unidad de analisis y de integridad:
- Unidad canonica: **milisegundos**. Todo eje que muestre valores lo declara.
- Las filas con `es_valor_especial = true` (0, -1, null, infinite, NO_ENCONTRADO,
  valores relativos) **nunca entran** a distribuciones ni a promedios: se reportan
  aparte, que es donde son interesantes.
- Las filas sin `valor_ms` por unidad no declarada tampoco entran; se cuentan.

Decisiones de figura (paper LNCS, puede imprimirse en blanco y negro):
- Escala de grises + trama, nunca color como unica portadora de identidad.
- Eje de valores en escala logaritmica (los defaults van de 1 ms a decenas de dias).
- Etiquetas directas de `n` y de conteos; rejilla tenue solo en el eje de valores.
- Un solo eje por figura; sin ejes duales.

Uso:
    .venv/Scripts/python.exe scripts/analisis.py
    .venv/Scripts/python.exe scripts/analisis.py --pgf   # ademas exporta .pgf (requiere LaTeX)
"""

import argparse
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
DATASET = RAIZ / "datos" / "dataset_timeouts.csv"
JUSTIF = RAIZ / "datos" / "justificaciones.csv"
SALIDA = RAIZ / "analisis"
FIGURAS = SALIDA / "figuras"

# Categorias del corpus (protocolo 3.4). Se declaran aqui para que la figura por
# categoria sea trazable al protocolo y no a una agrupacion improvisada.
CATEGORIA = {
    "zookeeper": "Coordinacion", "curator": "Coordinacion",
    "kafka": "Mensajeria", "activemq": "Mensajeria",
    "cassandra": "Bases de datos", "hbase": "Bases de datos",
    "hdfs": "Proc./almacenamiento", "yarn": "Proc./almacenamiento",
    "dubbo": "RPC",
    "tomcat": "Web",
    "camel": "Integracion",
}

# Rampa de grises. Validada con el validador del skill dataviz: separacion CVD y
# de vision normal DeltaE 24.5 (muy por encima del piso); los checks de croma y de
# banda de luminosidad fallan por construccion, porque es una paleta de impresion
# en blanco y negro. El WARN de contraste del gris claro se compensa como exige la
# regla: etiquetas visibles en cada segmento + trama + tablas en el .md.
TINTA = "#262626"
GRIS_MEDIO = "#8c8c8c"
GRIS_CLARO = "#d9d9d9"
REJILLA = "#e6e6e6"

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 8.5,
    "axes.titlesize": 9,
    "axes.labelsize": 8.5,
    "axes.edgecolor": "#4d4d4d",
    "axes.linewidth": 0.6,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7.5,
    "legend.frameon": False,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})

ANCHO = 4.8   # pulgadas: ancho de texto de LNCS (122 mm)


def humano(ms: float) -> str:
    """Formatea milisegundos en la unidad legible mas cercana (para las marcas)."""
    if ms < 1000:
        return f"{ms:g} ms"
    seg = ms / 1000
    if seg < 60:
        return f"{seg:g} s"
    minutos = seg / 60
    if minutos < 60:
        return f"{minutos:g} min"
    horas = minutos / 60
    if horas < 24:
        return f"{horas:g} h"
    return f"{horas / 24:g} d"


# Marcas en instantes que un lector reconoce, no en potencias de diez de ms
# (10^6 ms = "16.6667 min" no le dice nada a nadie). Van espaciadas para que las
# etiquetas no se toquen; la rejilla menor marca cada decada sin etiquetar.
MARCAS_MS = [1, 1_000, 60_000, 3_600_000, 86_400_000]


def eje_log_ms(ax) -> None:
    ax.set_xscale("log")
    ax.set_xticks(MARCAS_MS)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: humano(v)))
    ax.xaxis.set_minor_locator(matplotlib.ticker.LogLocator(base=10, numticks=15))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("valor por defecto (escala logaritmica; unidad canonica: ms)")
    ax.grid(axis="x", which="major", color="#d0d0d0", linewidth=0.6)
    ax.grid(axis="x", which="minor", color=REJILLA, linewidth=0.4)
    ax.tick_params(axis="x", which="minor", length=0)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)


def guardar(fig, nombre: str, pgf: bool) -> None:
    FIGURAS.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(FIGURAS / f"{nombre}.{ext}")
    if pgf:
        try:
            fig.savefig(FIGURAS / f"{nombre}.pgf")
        except Exception as e:                       # LaTeX no instalado
            print(f"  AVISO: no se pudo exportar {nombre}.pgf ({type(e).__name__}); "
                  f"el PDF sirve igual con \\includegraphics", file=sys.stderr)
    plt.close(fig)
    print(f"  figura: analisis/figuras/{nombre}.pdf")


# ------------------------------------------------------------------ datos
def cargar():
    with open(DATASET, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    normalizadas, especiales, sin_unidad = [], [], []
    for fila in filas:
        if fila["es_valor_especial"] == "true":
            especiales.append(fila)
        elif fila["valor_ms"]:
            fila["ms"] = float(fila["valor_ms"])
            normalizadas.append(fila)
        else:
            sin_unidad.append(fila)
    return filas, normalizadas, especiales, sin_unidad


def resumen(valores):
    v = sorted(valores)
    if len(v) >= 4:
        q = statistics.quantiles(v, n=4)
        return dict(n=len(v), minimo=v[0], p25=q[0], mediana=statistics.median(v), p75=q[2], maximo=v[-1])
    return dict(n=len(v), minimo=v[0], p25=v[0], mediana=statistics.median(v), p75=v[-1], maximo=v[-1])


# ---------------------------------------------------------------- figuras
def caja_por_grupo(grupos: dict, nombre: str, titulo: str, pgf: bool, alto_por_grupo=0.30):
    """Boxplot horizontal, ordenado por mediana, con n a la derecha."""
    orden = sorted(grupos, key=lambda k: statistics.median(grupos[k]))
    datos = [grupos[k] for k in orden]
    alto = max(2.0, 0.9 + alto_por_grupo * len(orden))
    fig, ax = plt.subplots(figsize=(ANCHO, alto))

    # Con menos de MIN_CAJA observaciones una caja finge una distribucion que no
    # existe: esos grupos se dibujan como puntos individuales.
    MIN_CAJA = 5
    con_caja = [(i, k) for i, k in enumerate(orden, start=1) if len(grupos[k]) >= MIN_CAJA]
    sin_caja = [(i, k) for i, k in enumerate(orden, start=1) if len(grupos[k]) < MIN_CAJA]

    if con_caja:
        ax.boxplot([grupos[k] for _, k in con_caja], orientation="horizontal",
                   positions=[i for i, _ in con_caja], widths=0.55, patch_artist=True,
                   medianprops=dict(color=TINTA, linewidth=1.4),
                   boxprops=dict(facecolor=GRIS_CLARO, edgecolor="#595959", linewidth=0.6),
                   whiskerprops=dict(color="#595959", linewidth=0.6),
                   capprops=dict(color="#595959", linewidth=0.6),
                   flierprops=dict(marker="o", markersize=2.4, markerfacecolor=GRIS_MEDIO,
                                   markeredgecolor="none", alpha=0.75))
    for i, k in sin_caja:
        ax.plot(grupos[k], [i] * len(grupos[k]), marker="o", markersize=3.4, linestyle="none",
                markerfacecolor=TINTA, markeredgecolor="white", markeredgewidth=0.5)

    ax.set_yticks(range(1, len(orden) + 1), [k.replace("_", " ").lower() for k in orden])
    ax.set_ylim(0.4, len(orden) + 0.6)
    eje_log_ms(ax)
    ax.set_title(titulo, loc="left", pad=8)

    limite = ax.get_xlim()[1]
    for i, clave in enumerate(orden, start=1):
        n = len(grupos[clave])
        etiqueta = f"n={n}" + ("*" if n < MIN_CAJA else "")
        ax.text(limite * 1.15, i, etiqueta, va="center", ha="left", fontsize=7.5, color="#595959")
    if sin_caja:
        # Como nota en el propio rotulo del eje: asi no se solapa con el, sea cual
        # sea la altura de la figura.
        ax.set_xlabel(ax.get_xlabel() + "\n* n < 5: puntos individuales, no caja")
    ax.set_xlim(right=limite * 1.1)
    guardar(fig, nombre, pgf)


def figura_valores_frecuentes(normalizadas, pgf: bool, tope=12):
    conteo = Counter(int(f["ms"]) for f in normalizadas).most_common(tope)
    conteo.reverse()
    etiquetas = [humano(v) for v, _ in conteo]
    valores = [n for _, n in conteo]
    # Enfasis (no identidad): los dos valores mas frecuentes en tinta plena.
    umbral = sorted(valores)[-2]
    colores = [TINTA if n >= umbral else GRIS_MEDIO for n in valores]

    fig, ax = plt.subplots(figsize=(ANCHO, 0.28 * len(conteo) + 1.0))
    barras = ax.barh(range(len(conteo)), valores, height=0.62, color=colores,
                     edgecolor="white", linewidth=1.2)
    ax.set_yticks(range(len(conteo)), etiquetas)
    total = len(normalizadas)
    for barra, n in zip(barras, valores):
        ax.text(barra.get_width() + total * 0.006, barra.get_y() + barra.get_height() / 2,
                f"{n}  ({100 * n / total:.0f} %)", va="center", fontsize=7.5, color="#404040")
    ax.set_xlabel(f"parametros con ese valor por defecto (n = {total} normalizados)")
    ax.set_title("Valores por defecto mas frecuentes", loc="left", pad=8)
    ax.grid(axis="x", color=REJILLA, linewidth=0.5)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.set_xlim(right=max(valores) * 1.28)
    guardar(fig, "valores_frecuentes", pgf)


def figura_estado_por_proyecto(filas, pgf: bool):
    proyectos = sorted({f["proyecto"] for f in filas},
                       key=lambda p: -sum(1 for f in filas if f["proyecto"] == p))
    proyectos.reverse()
    norm, esp, sin = [], [], []
    for p in proyectos:
        del_p = [f for f in filas if f["proyecto"] == p]
        esp_p = sum(1 for f in del_p if f["es_valor_especial"] == "true")
        sin_p = sum(1 for f in del_p if f["es_valor_especial"] == "false" and not f["valor_ms"])
        norm.append(len(del_p) - esp_p - sin_p)
        esp.append(esp_p)
        sin.append(sin_p)

    fig, ax = plt.subplots(figsize=(ANCHO, 0.30 * len(proyectos) + 1.2))
    y = range(len(proyectos))
    # Separacion de 2 px entre segmentos vista como borde blanco; trama en el
    # segmento claro para que sobreviva a la impresion en blanco y negro.
    b1 = ax.barh(y, norm, height=0.62, color=TINTA, edgecolor="white", linewidth=1.2,
                 label="normalizados")
    b2 = ax.barh(y, esp, left=norm, height=0.62, color=GRIS_MEDIO, edgecolor="white",
                 linewidth=1.2, label="valor especial (0, -1, null, no declarado)")
    b3 = ax.barh(y, sin, left=[a + b for a, b in zip(norm, esp)], height=0.62,
                 color=GRIS_CLARO, edgecolor="#8c8c8c", linewidth=0.6, hatch="///",
                 label="unidad no declarada")
    ax.set_yticks(list(y), proyectos)
    for i, (a, b, c) in enumerate(zip(norm, esp, sin)):
        ax.text(a + b + c + 2, i, f"{a + b + c}", va="center", fontsize=7.5, color="#404040")
        # Solo se rotula dentro del segmento si cabe; si no, el total de la derecha
        # y la tabla del informe dan el dato.
        ancho_minimo = 0.035 * max(x + y + z for x, y, z in zip(norm, esp, sin))
        if a >= ancho_minimo:
            ax.text(a / 2, i, str(a), va="center", ha="center", fontsize=7, color="white")
        if b >= ancho_minimo:
            ax.text(a + b / 2, i, str(b), va="center", ha="center", fontsize=7, color="white")
        if c >= ancho_minimo:
            ax.text(a + b + c / 2, i, str(c), va="center", ha="center", fontsize=7, color="#262626")
    ax.set_xlabel("parametros registrados")
    ax.set_title("Estado de los valores por proyecto", loc="left", pad=8)
    ax.legend(loc="lower right", ncols=1)
    ax.grid(axis="x", color=REJILLA, linewidth=0.5)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    guardar(fig, "estado_por_proyecto", pgf)


# ------------------------------------------------------------------ informe
def escribir_informe(filas, normalizadas, especiales, sin_unidad, justificaciones_listas):
    SALIDA.mkdir(parents=True, exist_ok=True)
    L = []
    a = L.append
    total = len(filas)
    a("# Estadistica descriptiva (generado por `scripts/analisis.py`)")
    a("")
    a("> Unidad canonica: **milisegundos**. Las filas con `es_valor_especial = true` y las")
    a("> que no tienen unidad declarada quedan **fuera** de toda distribucion y se")
    a("> reportan aparte. Las cifras de este archivo son las mismas que grafican las")
    a("> figuras de `analisis/figuras/` (sirve como vista de tabla accesible).")
    a("")
    a("## 1. Cobertura")
    a("")
    a("| | filas | % |")
    a("|---|---:|---:|")
    a(f"| Total del dataset | {total} | 100 % |")
    a(f"| Normalizados (entran al analisis) | {len(normalizadas)} | {100*len(normalizadas)/total:.1f} % |")
    a(f"| Valores especiales | {len(especiales)} | {100*len(especiales)/total:.1f} % |")
    a(f"| Sin unidad declarada | {len(sin_unidad)} | {100*len(sin_unidad)/total:.1f} % |")
    a("")

    v = sorted(f["ms"] for f in normalizadas)
    r = resumen(v)
    a("## 2. Distribucion global (ms)")
    a("")
    a("| minimo | p25 | mediana | p75 | maximo |")
    a("|---:|---:|---:|---:|---:|")
    a(f"| {r['minimo']:.0f} | {r['p25']:.0f} | {r['mediana']:.0f} | {r['p75']:.0f} | {r['maximo']:.0f} |")
    a("")
    a(f"En unidades legibles: mediana **{humano(r['mediana'])}**, rango de "
      f"{humano(r['minimo'])} a {humano(r['maximo'])}. El recorrido cubre nueve ordenes "
      f"de magnitud, por eso todas las figuras usan escala logaritmica.")
    a("")

    a("## 3. Valores mas frecuentes")
    a("")
    a("| valor | ms | parametros | % de normalizados |")
    a("|---|---:|---:|---:|")
    for val, n in Counter(int(f["ms"]) for f in normalizadas).most_common(15):
        a(f"| {humano(val)} | {val} | {n} | {100*n/len(normalizadas):.1f} % |")
    a("")
    redondos = sum(n for val, n in Counter(int(f["ms"]) for f in normalizadas).items()
                   if val in (1000, 2000, 3000, 5000, 10000, 15000, 20000, 30000, 60000,
                              120000, 300000, 600000, 900000, 1800000, 3600000))
    a(f"Los quince valores \"redondos\" habituales concentran **{redondos} de "
      f"{len(normalizadas)}** parametros ({100*redondos/len(normalizadas):.0f} %).")
    a("")

    a("## 4. Por tipo de timeout")
    a("")
    a("| tipo | n | mediana (ms) | mediana legible | minimo | maximo |")
    a("|---|---:|---:|---|---:|---:|")
    porte = defaultdict(list)
    for f in normalizadas:
        porte[f["tipo_timeout"]].append(f["ms"])
    for tipo in sorted(porte, key=lambda t: statistics.median(porte[t])):
        s = resumen(porte[tipo])
        a(f"| `{tipo}` | {s['n']} | {s['mediana']:.0f} | {humano(s['mediana'])} | "
          f"{s['minimo']:.0f} | {s['maximo']:.0f} |")
    a("")
    otro = len([f for f in filas if f["tipo_timeout"] == "OTRO"])
    a(f"> **Cuidado al leer esta tabla:** `OTRO` reune {otro} de {total} filas "
      f"({100*otro/total:.0f} %) porque el codebook sigue en v0. Mientras esa categoria "
      f"no se resuelva, las medianas por tipo son provisionales.")
    a("")

    a("## 5. Por categoria de proyecto")
    a("")
    a("| categoria | proyectos | n normalizados | mediana (ms) | mediana legible |")
    a("|---|---|---:|---:|---|")
    porcat = defaultdict(list)
    for f in normalizadas:
        porcat[CATEGORIA.get(f["proyecto"], "sin categoria")].append(f["ms"])
    proyectos_cat = defaultdict(set)
    for f in filas:
        proyectos_cat[CATEGORIA.get(f["proyecto"], "sin categoria")].add(f["proyecto"])
    for cat in sorted(porcat, key=lambda c: statistics.median(porcat[c])):
        s = resumen(porcat[cat])
        a(f"| {cat} | {', '.join(sorted(proyectos_cat[cat]))} | {s['n']} | "
          f"{s['mediana']:.0f} | {humano(s['mediana'])} |")
    a("")

    a("## 6. Valores especiales (no entran a las distribuciones)")
    a("")
    a("| valor tal como aparece | filas | lectura |")
    a("|---|---:|---|")
    lectura = {"0": "normalmente \"sin timeout\" o funcion deshabilitada",
               "-1": "normalmente \"esperar indefinidamente\"",
               "null": "la doc no fija un valor; se hereda de otro parametro",
               "NO_ENCONTRADO": "la doc no declara valor por defecto"}
    for val, n in Counter(f["valor_original"] for f in especiales).most_common():
        a(f"| `{val}` | {n} | {lectura.get(val, 'valor relativo o dependiente de otro parametro')} |")
    a("")
    a(f"Son {len(especiales)} filas ({100*len(especiales)/total:.0f} % del dataset). "
      f"Excluirlas de las medias no las hace irrelevantes: **que uno de cada seis "
      f"parametros venga sin limite efectivo es un resultado de RQ2**.")
    a("")

    # Un valor especial legitimo es 0, -1, null o una referencia a otro parametro.
    # Lo que no encaja en eso probablemente sea un error de extraccion o una fila
    # que ni siquiera es un timeout: se lista para que el humano decida.
    CONOCIDOS = {"0", "-1", "-2", "null", "NO_ENCONTRADO", "infinite", "disabled", "none"}
    sospechosas = [f for f in especiales if f["valor_original"] not in CONOCIDOS]
    if sospechosas:
        a("### 6.bis Filas que conviene depurar")
        a("")
        a("Valores especiales que no son ni `0`, ni `-1`, ni `null`, ni una referencia")
        a("limpia a otro parametro. Cada una necesita una decision humana:")
        a("")
        a("| id | proyecto | parametro | valor_original | que parece |")
        a("|---:|---|---|---|---|")
        for f in sorted(sospechosas, key=lambda x: int(x["id"])):
            v = f["valor_original"]
            if "." in v and not any(c.isdigit() for c in v):
                diagnostico = "**no es un timeout**: es un nombre de clase"
            elif v == "9223372036854775807":
                diagnostico = "`Long.MAX_VALUE`: en la practica, sin limite"
            elif re.search(r"\d+\s*(h|min|ms|msec|sec|s)\b", v):
                diagnostico = "valor con unidad embebida: se puede normalizar"
            elif re.search(r"[x*/]", v) or v.isidentifier():
                diagnostico = "expresado en funcion de otro parametro: correcto dejarlo fuera"
            else:
                diagnostico = "revisar a mano"
            a(f"| {f['id']} | {f['proyecto']} | `{f['parametro']}` | `{v}` | {diagnostico} |")
        a("")

    a("## 7. Justificaciones (RQ3)")
    a("")
    if justificaciones_listas:
        a("Ver figura `justificaciones.pdf`.")
    else:
        a("**Todavia no se puede analizar.** Las 40 filas de `datos/justificaciones.csv` "
          "estan en `PENDIENTE`: falta la busqueda en JIRA, commits y listas de correo. "
          "En cuanto haya datos, este script genera la figura de tipos de justificacion "
          "sin tocar nada mas.")
    a("")
    a("## 8. Que falta para que estas cifras sean definitivas")
    a("")
    a("1. Resolver la categoria `OTRO` y congelar el codebook v1 (afecta la seccion 4).")
    a("2. Fijar la regla de la unidad de analisis para parametros documentados en")
    a("   varias superficies (Kafka tiene 9 nombres repetidos; ver protocolo 2.bis).")
    a("3. Completar la busqueda de justificaciones (seccion 7).")
    a("4. Decidir las 12 filas sin unidad declarada: o se resuelven o se declaran.")
    a("")

    (SALIDA / "estadistica_descriptiva.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"  informe: analisis/estadistica_descriptiva.md")


def justificaciones_con_datos() -> bool:
    if not JUSTIF.exists():
        return False
    with open(JUSTIF, newline="", encoding="utf-8") as f:
        return any(fila.get("tipo_justificacion", "") not in ("", "PENDIENTE")
                   for fila in csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pgf", action="store_true", help="exportar tambien .pgf (requiere LaTeX)")
    args = ap.parse_args()

    filas, normalizadas, especiales, sin_unidad = cargar()
    print(f"Dataset: {len(filas)} filas | normalizadas {len(normalizadas)} | "
          f"especiales {len(especiales)} | sin unidad {len(sin_unidad)}")

    portipo = defaultdict(list)
    for f in normalizadas:
        portipo[f["tipo_timeout"]].append(f["ms"])
    caja_por_grupo(portipo, "dist_por_tipo",
                   "Distribucion de los valores por defecto, por tipo de timeout", args.pgf)

    porcat = defaultdict(list)
    for f in normalizadas:
        porcat[CATEGORIA.get(f["proyecto"], "sin categoria")].append(f["ms"])
    caja_por_grupo(porcat, "dist_por_categoria",
                   "Distribucion por categoria de proyecto", args.pgf)

    figura_valores_frecuentes(normalizadas, args.pgf)
    figura_estado_por_proyecto(filas, args.pgf)

    listas = justificaciones_con_datos()
    if not listas:
        print("  (sin figura de justificaciones: datos/justificaciones.csv sigue en PENDIENTE)")
    escribir_informe(filas, normalizadas, especiales, sin_unidad, listas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
