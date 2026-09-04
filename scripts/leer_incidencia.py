#!/usr/bin/env python3
"""Lee una incidencia del JIRA de ASF y muestra solo lo que sirve para RQ3.

Trae descripcion y comentarios, y filtra las frases que mencionan el parametro,
su valor por defecto o vocabulario de justificacion (medimos, elegimos, deberia
ser, arbitrario, por defecto...). Evita tener que leer hilos de cien comentarios
para encontrar la frase donde alguien explica de donde sale el numero.

Uso:
    python scripts/leer_incidencia.py KAFKA-3888 request.timeout.ms 30000
    python scripts/leer_incidencia.py HDFS-5400 dfs.client.mmap.cache.timeout.ms
"""

import json
import re
import sys
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://issues.apache.org/jira/rest/api/2/issue/"

JUSTIFICA = re.compile(
    r"\bdefault\b|\bwe (chose|picked|set|measured|tested|observed|found)\b|"
    r"\bshould be\b|\bmust be\b|\bat least\b|\bno (higher|lower) than\b|"
    r"\brule of thumb\b|\barbitrar\w*|\bconservative\b|\bsafe\b|\bexperiment\w*|"
    r"\bbenchmark\w*|\bin (our|my) (tests?|experience)\b|\btoo (short|long|low|high)\b|"
    r"\bincrease[d]? (it|the|to)\b|\bbump\w*\b|\bseconds?\b|\bminutes?\b|\bms\b", re.I)


def limpiar(texto: str) -> str:
    texto = re.sub(r"\{code[^}]*\}.*?\{code\}", " [bloque de codigo] ", texto or "", flags=re.S)
    texto = re.sub(r"\{noformat\}.*?\{noformat\}", " [salida de consola] ", texto, flags=re.S)
    return re.sub(r"\s+", " ", texto).strip()


def relevantes(texto: str, claves: list, tope: int = 6) -> list:
    frases = re.split(r"(?<=[.!?])\s+", limpiar(texto))
    salida = []
    for f in frases:
        if any(c and c.lower() in f.lower() for c in claves) and JUSTIFICA.search(f):
            salida.append(f[:500])
        if len(salida) >= tope:
            break
    return salida


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    clave_incidencia, parametro = sys.argv[1], sys.argv[2]
    valor = sys.argv[3] if len(sys.argv) > 3 else ""
    claves = [parametro, parametro.split(".")[-1], valor]

    url = (API + urllib.parse.quote(clave_incidencia) +
           "?fields=summary,created,resolution,description,comment")
    peticion = urllib.request.Request(url, headers={"User-Agent": "estudio-timeouts-espol"})
    with urllib.request.urlopen(peticion, timeout=40) as r:
        d = json.loads(r.read().decode("utf-8"))

    campos = d["fields"]
    print(f"{clave_incidencia}: {campos['summary']}")
    print(f"creada {campos['created'][:10]} | https://issues.apache.org/jira/browse/{clave_incidencia}")
    print()

    hallazgos = relevantes(campos.get("description") or "", claves)
    if hallazgos:
        print("DESCRIPCION:")
        for h in hallazgos:
            print(f"  - {h}")
        print()

    comentarios = (campos.get("comment") or {}).get("comments", [])
    print(f"COMENTARIOS ({len(comentarios)}):")
    encontrados = 0
    for c in comentarios:
        hs = relevantes(c.get("body") or "", claves, tope=2)
        if hs:
            autor = (c.get("author") or {}).get("displayName", "?")
            print(f"  [{c['created'][:10]} {autor}]")
            for h in hs:
                print(f"    - {h}")
            encontrados += 1
        if encontrados >= 8:
            print("  (mas comentarios con coincidencias; abrir la incidencia)")
            break
    if not encontrados:
        print("  ninguno menciona el parametro junto a vocabulario de justificacion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
