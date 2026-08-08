#!/usr/bin/env python3
"""Recupera `descripcion_oficial` para cada fila del dataset desde la evidencia
descargada en `datos/raw/` (no desde internet, no desde la memoria del modelo).

Un extractor por formato de documentación:
  hdfs, yarn   -> bloques <property><name><value><description> (hadoop *-default.xml)
  kafka        -> <h4>parametro</h4> + primer <p> (tablas de configuración)
  tomcat       -> <code class="attributeName">parametro</code> + celda siguiente
  zookeeper    -> item de lista "<em>parametro</em> : descripción"
  cassandra    -> <h2 id="parametro"> + párrafos previos a "Default Value"
  hbase        -> <div id="parametro" class="dlist"> + párrafo "Description"

Reglas de integridad:
- Si el parámetro no aparece en la evidencia, se escribe `NO_ENCONTRADO`
  (nunca se inventa ni se parafrasea de memoria).
- El texto se recorta a MAX_CHARS caracteres (la doc completa queda en `fuente_url`
  y en `datos/raw/`); el recorte se marca con " […]".
- No se modifica ninguna otra columna del dataset.

Uso:
    python scripts/extraer_descripciones.py                 # escribe el dataset
    python scripts/extraer_descripciones.py --dry-run       # solo reporta cobertura
"""

import csv
import html
import re
import shutil
import sys
from pathlib import Path

# La consola de Windows suele ser cp1252: evita que el reporte falle por "→", "…".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


RAIZ = Path(__file__).resolve().parent.parent
DATASET = RAIZ / "datos" / "dataset_timeouts.csv"
RAW = RAIZ / "datos" / "raw"

MAX_CHARS = 400
NO = "NO_ENCONTRADO"

# Archivos de evidencia por proyecto (en orden de búsqueda).
EVIDENCIA = {
    "hdfs": ["hdfs/config.html"],
    "yarn": ["yarn/config.html"],
    "kafka": [
        "kafka/kafka_config-3.9.html",
        "kafka/producer_config-3.9.html",
        "kafka/consumer_config-3.9.html",
        "kafka/documentation-3.9.html",
    ],
    "tomcat": ["tomcat/http-connector.html"],
    "zookeeper": ["zookeeper/zookeeperAdmin.html"],
    "cassandra": ["cassandra/config.html"],
    "hbase": ["hbase/config.html"],
}


def limpiar(fragmento: str) -> str:
    """Quita etiquetas, resuelve entidades, colapsa espacios y recorta."""
    texto = re.sub(r"<[^>]+>", " ", fragmento)
    texto = html.unescape(texto)
    texto = texto.replace("​", "").replace(" ", " ")
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > MAX_CHARS:
        corte = texto.rfind(" ", 0, MAX_CHARS)
        texto = texto[: corte if corte > 0 else MAX_CHARS].rstrip(" ,;.") + " […]"
    return texto


# --- extractores por formato -------------------------------------------------

def extraer_hadoop(doc: str, parametro: str) -> str:
    """<property> con <name>, <value>, <description> en cualquier orden."""
    for bloque in re.findall(r"<property>(.*?)</property>", doc, re.S):
        nombre = re.search(r"<name>\s*(.*?)\s*</name>", bloque, re.S)
        if not nombre or limpiar(nombre.group(1)) != parametro:
            continue
        desc = re.search(r"<description>(.*?)</description>", bloque, re.S)
        return limpiar(desc.group(1)) if desc else NO
    return NO


def extraer_kafka(doc: str, parametro: str) -> str:
    """<h4>…parametro…</h4> seguido del primer <p>…</p>."""
    patron = re.compile(r"<h4>(.*?)</h4>\s*<p>(.*?)</p>", re.S)
    for encabezado, cuerpo in patron.findall(doc):
        if limpiar(encabezado) == parametro:
            return limpiar(cuerpo)
    return NO


def extraer_tomcat(doc: str, parametro: str) -> str:
    """Fila de tabla: <code class="attributeName">parametro</code> + celda siguiente."""
    patron = re.compile(
        r'<code class="attributeName">%s</code>\s*</td>\s*<td>(.*?)</td>' % re.escape(parametro),
        re.S,
    )
    m = patron.search(doc)
    return limpiar(m.group(1)) if m else NO


def extraer_zookeeper(doc: str, parametro: str) -> str:
    """Item de lista con el nombre en cursiva: "<em>parametro</em> : descripción"."""
    patron = re.compile(r"<em>%s</em>\s*:?(.*?)</li>" % re.escape(parametro), re.S)
    m = patron.search(doc)
    if not m:
        return NO
    # Corta antes de notas/bloques anidados para quedarse con la definición.
    cuerpo = re.split(r"<h[1-6]>|<blockquote>|<ul>", m.group(1))[0]
    return limpiar(cuerpo) or NO


def extraer_cassandra(doc: str, parametro: str) -> str:
    """<h2 id="parametro"> … párrafos hasta "Default Value"."""
    patron = re.compile(
        r'<h2 id="%s">.*?</h2>(.*?)(?:<em>Default Value|<h2 |\Z)' % re.escape(parametro), re.S
    )
    m = patron.search(doc)
    if not m:
        return NO
    parrafos = re.findall(r"<p>(.*?)</p>", m.group(1), re.S)
    # Descarta el aviso "This option is commented out by default." si hay más texto.
    utiles = [p for p in parrafos if "commented out by default" not in p] or parrafos
    return limpiar(" ".join(utiles)) or NO


def extraer_hbase(doc: str, parametro: str) -> str:
    """<div id="parametro" class="dlist"> … <div class="title">Description</div><p>…</p>."""
    patron = re.compile(
        r'<div id="%s" class="dlist">(.*?)</dl>' % re.escape(parametro), re.S
    )
    m = patron.search(doc)
    if not m:
        return NO
    desc = re.search(r'<div class="title">Description</div>\s*<p>(.*?)</p>', m.group(1), re.S)
    return limpiar(desc.group(1)) if desc else NO


EXTRACTORES = {
    "hdfs": extraer_hadoop,
    "yarn": extraer_hadoop,
    "kafka": extraer_kafka,
    "tomcat": extraer_tomcat,
    "zookeeper": extraer_zookeeper,
    "cassandra": extraer_cassandra,
    "hbase": extraer_hbase,
}


def cargar_evidencia() -> dict:
    docs = {}
    for proyecto, archivos in EVIDENCIA.items():
        textos = []
        for rel in archivos:
            ruta = RAW / rel
            if not ruta.exists():
                print(f"AVISO: falta evidencia {ruta}", file=sys.stderr)
                continue
            textos.append(ruta.read_text(encoding="utf-8", errors="replace"))
        docs[proyecto] = textos
    return docs


def main() -> int:
    dry = "--dry-run" in sys.argv
    docs = cargar_evidencia()

    with open(DATASET, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas = list(lector.fieldnames)
        filas = list(lector)

    if "descripcion_oficial" not in columnas:
        # Se inserta antes de fuente_url para respetar el orden del protocolo.
        pos = columnas.index("fuente_url") if "fuente_url" in columnas else len(columnas)
        columnas.insert(pos, "descripcion_oficial")

    encontradas, faltantes, conservadas = 0, [], []
    for fila in filas:
        proyecto = fila["proyecto"]
        extractor = EXTRACTORES.get(proyecto)
        if extractor is None:
            # Proyectos extraidos por otro script (p. ej. extraer_timeouts_s4.py ya
            # trae descripcion_oficial): se conserva lo que haya, no se borra.
            previa = fila.get("descripcion_oficial", "")
            fila["descripcion_oficial"] = previa
            if previa and previa != NO:
                conservadas.append(f"{proyecto}/{fila['parametro']}")
                encontradas += 1
            else:
                faltantes.append((fila["id"], proyecto, fila["parametro"], "sin extractor"))
            continue
        texto = NO
        for doc in docs.get(proyecto, []):
            texto = extractor(doc, fila["parametro"])
            if texto != NO:
                break
        fila["descripcion_oficial"] = texto
        if texto == NO:
            faltantes.append((fila["id"], proyecto, fila["parametro"], "no aparece en evidencia"))
        else:
            encontradas += 1

    print(f"Filas: {len(filas)} | con descripcion_oficial: {encontradas} | {NO}: {len(faltantes)}")
    if conservadas:
        print(f"  conservadas de otro extractor (no se re-extraen): {len(conservadas)}")
    por_proyecto = {}
    for fila in filas:
        p = fila["proyecto"]
        ok = fila["descripcion_oficial"] != NO
        d = por_proyecto.setdefault(p, [0, 0])
        d[0] += ok
        d[1] += 1
    for p, (ok, total) in sorted(por_proyecto.items()):
        print(f"  {p:<10} {ok}/{total}")
    for id_, proyecto, parametro, motivo in faltantes:
        print(f"  {NO} id={id_} {proyecto}/{parametro}: {motivo}", file=sys.stderr)

    if dry:
        print("(--dry-run: no se escribió el dataset)")
        return 0

    shutil.copy2(DATASET, str(DATASET) + ".bak")
    with open(DATASET, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"Escrito {DATASET} (respaldo en {DATASET.name}.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
