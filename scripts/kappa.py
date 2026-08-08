#!/usr/bin/env python3
"""Acuerdo inter-anotador sobre la muestra de validación (semana 4).

Cohen's kappa con 2 anotadores; Fleiss' kappa con 3 o más. Solo biblioteca
estándar (sin numpy/sklearn) para que el cálculo sea auditable línea por línea.

Entradas (se unen por `id_muestra`):
  validacion/clave_muestra_anotador2.csv   -> columna `tipo_timeout_anotador1`
  validacion/muestra_anotador2.csv         -> columna `tipo_timeout_anotador2`
  validacion/muestra_anotador3.csv (opc.)  -> columna `tipo_timeout_anotador3`  ...

Salidas: reporte por consola (acuerdo observado, esperado, kappa, interpretación,
matriz de confusión, kappa por categoría y lista de desacuerdos) y, con `--md`,
el mismo reporte en Markdown para pegar/enlazar en `validacion/kappa_resultados.md`.

Reglas:
- Las filas con alguna etiqueta vacía se excluyen y se reportan aparte
  (no se imputa ninguna etiqueta).
- Las filas de calentamiento se excluyen con `--excluir M001,M002` (no cuentan
  para kappa, ver guía de anotación).

Uso:
    python scripts/kappa.py
    python scripts/kappa.py --excluir M007,M031 --md validacion/kappa_generado.md
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

# La consola de Windows suele ser cp1252: evita que el reporte falle por "→", "…".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


RAIZ = Path(__file__).resolve().parent.parent
VALIDACION = RAIZ / "validacion"
CLAVE = VALIDACION / "clave_muestra_anotador2.csv"

# Escala de referencia. TODO-HUMANO: verificar la cita exacta (Landis & Koch 1977)
# en Scholar/DOI antes de usarla en el paper (ver protocolo §8).
ESCALA = [
    (0.81, "casi perfecto"),
    (0.61, "sustancial"),
    (0.41, "moderado"),
    (0.21, "razonable (fair)"),
    (0.00, "leve (slight)"),
    (-1.0, "peor que el azar"),
]


def interpretar(k: float) -> str:
    for umbral, etiqueta in ESCALA:
        if k >= umbral:
            return etiqueta
    return "indeterminado"


def cargar_anotaciones() -> tuple:
    """Devuelve (etiquetas_por_anotador, nombres, vacias) alineadas por id_muestra."""
    if not CLAVE.exists():
        raise SystemExit(f"Falta {CLAVE.relative_to(RAIZ)} (genera la muestra con scripts/muestrear.py)")

    with open(CLAVE, newline="", encoding="utf-8") as f:
        clave = {fila["id_muestra"]: fila for fila in csv.DictReader(f)}

    columnas = {1: ("tipo_timeout_anotador1", CLAVE)}
    datos = {1: {idm: fila["tipo_timeout_anotador1"].strip() for idm, fila in clave.items()}}

    n_anotador = 2
    while True:
        ruta = VALIDACION / (
            "muestra_anotador2.csv" if n_anotador == 2 else f"muestra_anotador{n_anotador}.csv"
        )
        if not ruta.exists():
            break
        col = f"tipo_timeout_anotador{n_anotador}"
        with open(ruta, newline="", encoding="utf-8") as f:
            lector = csv.DictReader(f)
            if col not in (lector.fieldnames or []):
                raise SystemExit(f"{ruta.name} no tiene la columna {col}")
            datos[n_anotador] = {
                fila["id_muestra"]: fila[col].strip() for fila in lector
            }
        columnas[n_anotador] = (col, ruta)
        n_anotador += 1

    if len(datos) < 2:
        raise SystemExit("Se necesitan al menos 2 anotadores (falta muestra_anotador2.csv)")

    ids = sorted(set.intersection(*(set(d) for d in datos.values())))
    vacias = [i for i in ids if any(not datos[a].get(i) for a in datos)]
    return datos, columnas, ids, vacias


def cohen(a: list, b: list) -> tuple:
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    k = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return po, pe, k


def fleiss(matriz: list, categorias: list) -> tuple:
    """matriz: una fila por ítem con el conteo de votos por categoría."""
    n_items = len(matriz)
    m = sum(matriz[0])
    if any(sum(fila) != m for fila in matriz):
        raise SystemExit("Fleiss requiere el mismo número de anotadores por ítem")
    p_j = [sum(fila[j] for fila in matriz) / (n_items * m) for j in range(len(categorias))]
    p_i = [(sum(c * c for c in fila) - m) / (m * (m - 1)) for fila in matriz]
    po = sum(p_i) / n_items
    pe = sum(p * p for p in p_j)
    k = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return po, pe, k


def reporte(datos, columnas, ids, vacias, excluir, ruta_md=None) -> None:
    usables = [i for i in ids if i not in excluir and i not in vacias]
    lineas = []

    def out(texto=""):
        print(texto)
        lineas.append(texto)

    anotadores = sorted(datos)
    out(f"# Acuerdo inter-anotador (generado por scripts/kappa.py)")
    out()
    out(f"- Anotadores: {len(anotadores)} ({', '.join(columnas[a][0] for a in anotadores)})")
    out(f"- Filas en la muestra: {len(ids)}")
    def listar(items: list, tope: int = 10) -> str:
        items = list(items)
        if not items:
            return ""
        visibles = ", ".join(items[:tope])
        return f"({visibles}{', …' if len(items) > tope else ''})"

    out(f"- Excluidas por calentamiento: {len(excluir & set(ids))} {listar(sorted(excluir & set(ids)))}")
    out(f"- Excluidas por etiqueta vacía: {len(vacias)} {listar(vacias)}")
    out(f"- Filas usadas para kappa: {len(usables)}")
    out()

    if not usables:
        out("**Sin filas anotadas todavía**: el kappa no se puede calcular.")
        if ruta_md:
            Path(ruta_md).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return

    etiquetas = {a: [datos[a][i] for i in usables] for a in anotadores}
    categorias = sorted({e for lista in etiquetas.values() for e in lista})

    if len(anotadores) == 2:
        po, pe, k = cohen(etiquetas[1], etiquetas[2])
        out(f"## Cohen's kappa")
    else:
        matriz = []
        for idx in range(len(usables)):
            fila = [0] * len(categorias)
            for a in anotadores:
                fila[categorias.index(etiquetas[a][idx])] += 1
            matriz.append(fila)
        po, pe, k = fleiss(matriz, categorias)
        out(f"## Fleiss' kappa")
    out()
    out(f"- Acuerdo observado (Po): {po:.4f}")
    out(f"- Acuerdo esperado por azar (Pe): {pe:.4f}")
    out(f"- **kappa = {k:.4f}** → acuerdo *{interpretar(k)}* (escala de referencia, ver protocolo §8)")
    out()

    if len(anotadores) == 2:
        out("## Matriz de confusión (filas: anotador 1, columnas: anotador 2)")
        out()
        conteo = defaultdict(int)
        for x, y in zip(etiquetas[1], etiquetas[2]):
            conteo[(x, y)] += 1
        ancho = max(len(c) for c in categorias)
        esquina = "anot1 / anot2".ljust(ancho)
        out("| " + " | ".join([esquina] + categorias) + " |")
        out("|" + "---|" * (len(categorias) + 1))
        for f_cat in categorias:
            celdas = [str(conteo[(f_cat, c)]) if conteo[(f_cat, c)] else "" for c in categorias]
            out("| " + " | ".join([f"{f_cat:<{ancho}}"] + celdas) + " |")
        out()

        out("## Kappa por categoría (una contra el resto)")
        out()
        out("| categoría | n (anot1) | n (anot2) | kappa | interpretación |")
        out("|---|---|---|---|---|")
        for cat in categorias:
            bin1 = [1 if e == cat else 0 for e in etiquetas[1]]
            bin2 = [1 if e == cat else 0 for e in etiquetas[2]]
            _, _, kc = cohen(bin1, bin2)
            out(f"| `{cat}` | {sum(bin1)} | {sum(bin2)} | {kc:.4f} | {interpretar(kc)} |")
        out()

        desacuerdos = [
            (i, datos[1][i], datos[2][i]) for i in usables if datos[1][i] != datos[2][i]
        ]
        out(f"## Desacuerdos a resolver ({len(desacuerdos)})")
        out()
        if desacuerdos:
            out("| id_muestra | anotador 1 | anotador 2 | resolución (HUMANO) |")
            out("|---|---|---|---|")
            for idm, e1, e2 in desacuerdos:
                out(f"| {idm} | `{e1}` | `{e2}` | PENDIENTE |")
        else:
            out("Ninguno.")
        out()
        out("> Cada desacuerdo se discute y la decisión se documenta en el codebook (v2).")

    if ruta_md:
        Path(ruta_md).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        print(f"\nReporte escrito en {ruta_md}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excluir", default="", help="ids de calentamiento separados por coma (M001,M002)")
    ap.add_argument("--md", default=None, help="ruta donde escribir el reporte en Markdown")
    args = ap.parse_args()

    excluir = {x.strip() for x in args.excluir.split(",") if x.strip()}
    datos, columnas, ids, vacias = cargar_anotaciones()
    reporte(datos, columnas, ids, vacias, excluir, args.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
