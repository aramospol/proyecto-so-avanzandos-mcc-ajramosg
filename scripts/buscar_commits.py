#!/usr/bin/env python3
"""RQ3, segundo canal: historia de commits del proyecto.

El protocolo pone la historia del archivo de valores por defecto por delante del
sistema de incidencias, porque el commit que fija el numero suele explicarlo o
apuntar al issue que lo hace. Este guion busca cada parametro de la muestra en los
mensajes de commit del repositorio oficial (API de busqueda de GitHub, sin
autenticar) y guarda lo que encuentra.

Limite de la API sin autenticar: 10 busquedas por minuto, de ahi la pausa.

Salida: `datos/raw/justificaciones/COMMITS.md` y un JSON por parametro.

Uso:  python scripts/buscar_commits.py
"""

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
SALIDA = EVIDENCIA / "COMMITS.md"

REPO = {"kafka": "apache/kafka", "hdfs": "apache/hadoop", "yarn": "apache/hadoop",
        "cassandra": "apache/cassandra", "zookeeper": "apache/zookeeper",
        "tomcat": "apache/tomcat", "hbase": "apache/hbase", "camel": "apache/camel",
        "activemq": "apache/activemq", "dubbo": "apache/dubbo", "curator": "apache/curator"}

RAZON = re.compile(
    r"\bwhy\b|\bbecause\b|\bmeasur\w+|\bbenchmark\w*|\btoo (short|long|low|high|small|big)\b|"
    r"\bincrease\w*\b|\bdecrease\w*\b|\bbump\w*\b|\btun(e|ing)\b|\bdefault\w*\b|"
    r"\barbitrar\w+|\bsafe\b|\bconservative\b|\bmatch\w*\b|\bconsistent\b", re.I)


def buscar(repo: str, termino: str) -> dict:
    q = urllib.parse.quote(f"repo:{repo} {termino}")
    url = f"https://api.github.com/search/commits?q={q}&per_page=5"
    pet = urllib.request.Request(url, headers={
        "User-Agent": "estudio-timeouts-espol", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(pet, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    EVIDENCIA.mkdir(parents=True, exist_ok=True)
    with open(MUESTRA, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    doc = ["# Historia de commits por parametro (RQ3)", "",
           "Commits del repositorio oficial cuyo mensaje menciona el parametro.",
           "`[RAZON]` marca mensajes con vocabulario que sugiere explicacion del valor.",
           "Buscado con la API de GitHub, sin autenticar.", ""]
    con_resultados = 0

    for i, fila in enumerate(filas, start=1):
        proyecto, parametro = fila["proyecto"], fila["parametro"]
        repo = REPO.get(proyecto)
        print(f"  [{i}/{len(filas)}] {proyecto}/{parametro}", flush=True)
        doc.append(f"## {proyecto} / `{parametro}` = {fila['valor_original']} {fila['unidad_original']}")
        doc.append("")
        if not repo:
            doc += ["Repositorio desconocido.", ""]
            continue
        try:
            d = buscar(repo, parametro)
        except Exception as e:
            doc += [f"Error de consulta: {type(e).__name__}.", ""]
            time.sleep(8)
            continue

        (EVIDENCIA / f"commits_{proyecto}_{parametro}.json").write_text(
            json.dumps(d, indent=1)[:200000], encoding="utf-8")
        total = d.get("total_count", 0)
        doc.append(f"Commits que lo mencionan: **{total}**")
        if total:
            con_resultados += 1
            for it in d.get("items", [])[:5]:
                msg = it["commit"]["message"].splitlines()[0]
                marca = " [RAZON]" if RAZON.search(it["commit"]["message"]) else ""
                doc.append(f"- [`{it['sha'][:8]}`]({it['html_url']}) "
                           f"{it['commit']['author']['date'][:10]} {msg[:110]}{marca}")
        doc.append("")
        time.sleep(7)   # 10 busquedas por minuto sin autenticar

    SALIDA.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"\nParametros con al menos un commit: {con_resultados}/{len(filas)}")
    print(f"Escrito {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
