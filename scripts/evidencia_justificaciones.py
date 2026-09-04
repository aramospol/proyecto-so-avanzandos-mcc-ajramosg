#!/usr/bin/env python3
"""RQ3/RQ4, segundo paso: de las incidencias candidatas, saca las frases donde
alguien habla del valor.

Toma los JSON que dejo `buscar_justificaciones.py`, abre cada incidencia candidata
(descripcion y comentarios) y puntua sus frases. Gana la que menciona el valor por
defecto junto a vocabulario de justificacion. La idea es no leer hilos enteros para
encontrar la frase donde se explica de donde sale el numero.

Puntuacion por frase:
  +3 el valor por defecto (en cualquiera de sus formas: 30000, 30 seconds, 30s)
  +2 el nombre del parametro
  +2 vocabulario fuerte (measured, benchmark, we chose, safe, arbitrary, too short)
  +1 la palabra default

Salida: `datos/raw/justificaciones/EVIDENCIA.md`, con las mejores frases por
parametro y el enlace a la incidencia. La etiqueta la decide una persona leyendo eso.

Uso:  python scripts/evidencia_justificaciones.py [--max-incidencias 4]
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
MUESTRA = RAIZ / "datos" / "justificaciones.csv"
EVIDENCIA = RAIZ / "datos" / "raw" / "justificaciones"
SALIDA = EVIDENCIA / "EVIDENCIA.md"
API = "https://issues.apache.org/jira/rest/api/2/issue/"

FUERTE = re.compile(
    r"\bwe (chose|picked|set|measured|tested|observed|found|decided)\b|\bi (chose|picked|prefer)\b|"
    r"\bmeasur\w+|\bbenchmark\w*|\bexperiment\w*|\bin (our|my) (tests?|experience|benchmarks?)\b|"
    r"\bsafe side\b|\bconservative\b|\barbitrar\w+|\brule of thumb\b|\bheuristic\w*|"
    r"\btoo (short|long|low|high|small|big)\b|\bshould be (at least|no (more|higher|lower))\b|"
    r"\bsame as\b|\bconsistent with\b|\bmatch(es|ing)? the\b|\bbackward[s]? compat\w*", re.I)
DEFECTO = re.compile(r"\bdefault\w*\b", re.I)


def variantes_valor(valor: str, unidad: str) -> list:
    """30000 ms -> ['30000', '30 second', '30s', '30 sec']. Ayuda a encontrar la
    frase donde se nombra el valor aunque este escrito en otra unidad."""
    v = (valor or "").strip()
    if not v or v in ("NO_ENCONTRADO", "null", "0"):
        return [x for x in (v,) if x]
    out = {v}
    try:
        n = float(v)
    except ValueError:
        return list(out)
    if unidad == "ms" and n >= 1000 and n % 1000 == 0:
        s = int(n // 1000)
        out |= {f"{s} second", f"{s} sec", f"{s}s"}
        if s % 60 == 0:
            out |= {f"{s // 60} minute", f"{s // 60} min"}
    if unidad == "s":
        out |= {f"{int(n)} second", f"{int(n)}s"}
    if unidad == "h":
        out |= {f"{int(n)} hour", f"{int(n)}h"}
        if n % 24 == 0:
            out.add(f"{int(n // 24)} day")
    return list(out)


def limpiar(texto: str) -> str:
    texto = re.sub(r"\{code[^}]*\}.*?\{code\}", " ", texto or "", flags=re.S)
    texto = re.sub(r"\{noformat\}.*?\{noformat\}", " ", texto, flags=re.S)
    texto = re.sub(r"https?://\S+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def puntuar(frase: str, parametro: str, valores: list) -> int:
    p = 0
    if any(v.lower() in frase.lower() for v in valores if v):
        p += 3
    if parametro.lower() in frase.lower():
        p += 2
    if FUERTE.search(frase):
        p += 2
    if DEFECTO.search(frase):
        p += 1
    return p


def traer(clave: str) -> dict:
    url = API + urllib.parse.quote(clave) + "?fields=summary,created,description,comment"
    pet = urllib.request.Request(url, headers={"User-Agent": "estudio-timeouts-espol"})
    with urllib.request.urlopen(pet, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-incidencias", type=int, default=4)
    ap.add_argument("--pausa", type=float, default=0.6)
    args = ap.parse_args()

    with open(MUESTRA, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    doc = ["# Evidencia por parametro (RQ3/RQ4)", "",
           "Frases mejor puntuadas de las incidencias candidatas. Puntuacion alta =",
           "menciona el valor por defecto junto a vocabulario de justificacion.",
           "**No es una clasificacion**: es lo que hay que leer para decidirla.", ""]

    for i, fila in enumerate(filas, start=1):
        proyecto, parametro = fila["proyecto"], fila["parametro"]
        valores = variantes_valor(fila["valor_original"], fila["unidad_original"])
        ruta = EVIDENCIA / f"{proyecto}_{parametro}.json"
        print(f"  [{i}/{len(filas)}] {proyecto}/{parametro}", flush=True)
        doc.append(f"## {proyecto} / `{parametro}` = {fila['valor_original']} {fila['unidad_original']}")

        if not ruta.exists():
            doc += ["", "Sin candidatas (proyecto sin JIRA de ASF o sin resultados).", ""]
            continue

        candidatas = json.loads(ruta.read_text(encoding="utf-8")).get("issues", [])[: args.max_incidencias]
        if not candidatas:
            doc += ["", "Ninguna incidencia menciona el parametro.", ""]
            continue

        mejores = []
        for inc in candidatas:
            clave = inc["key"]
            try:
                d = traer(clave)
            except Exception:
                continue
            time.sleep(args.pausa)
            campos = d["fields"]
            piezas = [("descripcion", campos.get("description") or "")]
            for c in (campos.get("comment") or {}).get("comments", []):
                piezas.append((f"comentario {c['created'][:10]}", c.get("body") or ""))
            for origen, texto in piezas:
                # Ventana de dos frases: la justificacion suele partirse entre la
                # frase que da el numero y la siguiente que da el motivo
                # ("subio de 200 a 500 ms. Se que es alto, pero prefiero ir seguro").
                frases = [f for f in re.split(r"(?<=[.!?])\s+", limpiar(texto)) if len(f) > 15]
                ventanas = frases + [f"{a} {b}" for a, b in zip(frases, frases[1:])]
                for frase in ventanas:
                    if len(frase) < 30 or len(frase) > 800:
                        continue
                    p = puntuar(frase, parametro, valores)
                    if p >= 5:
                        mejores.append((p, clave, origen, frase))
        mejores.sort(key=lambda x: -x[0])
        doc.append("")
        if not mejores:
            doc += ["Nada con puntuacion suficiente en las candidatas revisadas.", ""]
            continue
        vistos = set()
        for p, clave, origen, frase in mejores:
            if frase[:80] in vistos:
                continue
            vistos.add(frase[:80])
            doc.append(f"- **{p}** [{clave}](https://issues.apache.org/jira/browse/{clave}) "
                       f"({origen}): {frase[:450]}")
            if len(vistos) >= 3:
                break
        doc.append("")

    SALIDA.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"\nEscrito {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
