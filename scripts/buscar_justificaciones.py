#!/usr/bin/env python3
"""RQ3/RQ4: rastrea en el JIRA de ASF el origen del valor por defecto de cada
parametro de la muestra de `datos/justificaciones.csv`.

Este guion NO clasifica ni decide: solo recupera evidencia y la deja lista para
que una persona la lea. Por cada parametro consulta el JIRA con busqueda de frase
exacta, guarda el JSON crudo como evidencia en
`datos/raw/justificaciones/<proyecto>_<parametro>.json` y escribe un archivo de
triaje con los fragmentos de texto donde se menciona el parametro.

La clasificacion (EXPERIMENTO / HEURISTICA / HERENCIA / ARBITRARIO / NO_ENCONTRADO)
se hace leyendo esos fragmentos y abriendo la incidencia; nunca desde el titulo.

Tomcat no usa el JIRA de ASF sino Bugzilla, asi que sus filas se marcan para
busqueda aparte.

Uso:
    python scripts/buscar_justificaciones.py            # todos los pendientes
    python scripts/buscar_justificaciones.py --limite 5 # prueba corta
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
TRIAJE = EVIDENCIA / "TRIAJE.md"

JIRA = "https://issues.apache.org/jira/rest/api/2/search"
PROYECTO_JIRA = {
    "kafka": "KAFKA", "hdfs": "HDFS", "yarn": "YARN",
    "cassandra": "CASSANDRA", "zookeeper": "ZOOKEEPER", "hbase": "HBASE",
    "activemq": "AMQ", "camel": "CAMEL", "dubbo": "DUBBO", "curator": "CURATOR",
}
SIN_JIRA = {"tomcat": "Bugzilla (bz.apache.org), no JIRA"}

# Palabras que sugieren que ahi se discute el POR QUE del numero.
SENAL = re.compile(
    r"default|why|too (short|long|low|high)|increase|decrease|bump|tune|tuning|"
    r"benchmark|measured|test(ed|ing)? show|rule of thumb|arbitrar|safe|conservative",
    re.I)


def consultar(jql: str, campos: str, maximo: int = 6) -> dict:
    url = JIRA + "?" + urllib.parse.urlencode(
        {"jql": jql, "maxResults": maximo, "fields": campos})
    peticion = urllib.request.Request(url, headers={"User-Agent": "estudio-timeouts-espol"})
    with urllib.request.urlopen(peticion, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def fragmentos(texto: str, parametro: str, valor: str, tope: int = 3) -> list:
    """Frases del texto donde aparece el parametro o su valor por defecto."""
    if not texto:
        return []
    texto = re.sub(r"\s+", " ", texto)
    frases = re.split(r"(?<=[.!?])\s+", texto)
    utiles = []
    for f in frases:
        if parametro in f or (valor and valor not in ("NO_ENCONTRADO", "") and valor in f):
            marca = " [SENAL]" if SENAL.search(f) else ""
            utiles.append(f.strip()[:400] + marca)
        if len(utiles) >= tope:
            break
    return utiles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limite", type=int, default=0, help="procesar solo N filas (prueba)")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre consultas")
    args = ap.parse_args()

    EVIDENCIA.mkdir(parents=True, exist_ok=True)
    with open(MUESTRA, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    pendientes = [r for r in filas if r["tipo_justificacion"] in ("PENDIENTE", "")]
    if args.limite:
        pendientes = pendientes[: args.limite]
    print(f"Parametros a rastrear: {len(pendientes)}")

    salida = ["# Triaje de justificaciones (RQ3/RQ4)",
              "",
              "Generado por `scripts/buscar_justificaciones.py`. Cada bloque lista las",
              "incidencias del JIRA de ASF que mencionan el parametro, con los fragmentos",
              "donde aparece. `[SENAL]` marca frases que hablan de valores, ajustes o",
              "mediciones: son las que hay que leer primero.",
              "",
              "**Esto es materia prima, no una clasificacion.** La etiqueta se decide",
              "abriendo la incidencia y leyendola.",
              ""]

    con_candidatos = 0
    for i, fila in enumerate(pendientes, start=1):
        proyecto, parametro = fila["proyecto"], fila["parametro"]
        valor = fila["valor_original"]
        print(f"  [{i}/{len(pendientes)}] {proyecto}/{parametro}", flush=True)
        salida.append(f"## {proyecto} / `{parametro}` = {valor} {fila['unidad_original']}")
        salida.append("")

        if proyecto in SIN_JIRA:
            salida += [f"Sin rastro automatico: {SIN_JIRA[proyecto]}.", ""]
            continue

        clave = PROYECTO_JIRA.get(proyecto)
        jql = f'project={clave} AND text ~ "\\"{parametro}\\"" ORDER BY created ASC'
        try:
            datos = consultar(jql, "key,summary,created,description")
        except Exception as e:
            salida += [f"Error de consulta: {type(e).__name__}.", ""]
            continue

        (EVIDENCIA / f"{proyecto}_{parametro}.json").write_text(
            json.dumps(datos, indent=1), encoding="utf-8")

        total = datos.get("total", 0)
        salida.append(f"Incidencias que lo mencionan: **{total}** "
                      f"(JQL: `{jql}`)")
        salida.append("")
        if not datos.get("issues"):
            salida += ["Ninguna.", ""]
            continue
        con_candidatos += 1
        for inc in datos["issues"]:
            k = inc["key"]
            campos = inc["fields"]
            salida.append(f"- **[{k}](https://issues.apache.org/jira/browse/{k})** "
                          f"({campos['created'][:10]}) {campos['summary'][:90]}")
            for frag in fragmentos(campos.get("description") or "", parametro, valor):
                salida.append(f"  - {frag}")
        salida.append("")
        time.sleep(args.pausa)

    TRIAJE.write_text("\n".join(salida) + "\n", encoding="utf-8")
    print(f"\nParametros con al menos una incidencia: {con_candidatos}/{len(pendientes)}")
    print(f"Triaje en {TRIAJE.relative_to(RAIZ)}")
    print("Evidencia cruda (JSON) en datos/raw/justificaciones/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
