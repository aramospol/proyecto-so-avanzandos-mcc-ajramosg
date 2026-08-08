#!/usr/bin/env python3
"""Semana 4 (ampliacion del corpus): extrae timeouts de ActiveMQ, Dubbo, Camel y
Curator del HTML crudo en datos/raw/ y los ANEXA a datos/dataset_timeouts.csv.

Mismo metodo que las semanas 2-3: no se ejecuta ningun proyecto, los valores son
los que la documentacion declara. Un parser por formato de tabla:

  activemq -> tablas "Option Name | Default Value | Description" de las paginas de
              referencia de transportes y de la URI de conexion.
  dubbo    -> tablas "Attribute | URL parameter | Type | Required | Default | ...
              | descripcion | desde version" del Configuration Item Reference Manual.
  camel    -> tablas "Name | Description | Default | Type" de las paginas de
              componente; se EXCLUYEN las filas de Spring Boot (camel.component.*)
              porque duplican la misma opcion con otro prefijo.
  curator  -> javadoc: solo los parametros cuyo texto declara explicitamente un
              default ("The default is ..."). Curator casi no publica sus valores.

Thrift NO se extrae: su documentacion oficial no publica parametros de
configuracion ni valores por defecto (criterio E2 del protocolo). Ver
datos/raw/thrift/FUENTES.md.

Reglas de integridad respetadas:
- valor_original y unidad_original se conservan tal como aparecen, separados.
- es_valor_especial = true para 0, negativos, vacio, "infinite"/"disabled"/"none".
- tipo_timeout es una PROPUESTA por palabras clave; requiere revision humana
  (queda marcado en notas).
- descripcion_oficial se recorta a 400 caracteres; la fuente completa queda en raw.
- Idempotente: descarta las filas previas de estos 4 proyectos antes de anexar.

Uso:
    python scripts/extraer_timeouts_s4.py --dry-run
    python scripts/extraer_timeouts_s4.py
"""

import csv
import html as H
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
DATASET = RAIZ / "datos" / "dataset_timeouts.csv"
RAW = RAIZ / "datos" / "raw"
FECHA = "2026-08-08"
PROYECTOS = {"activemq", "dubbo", "camel", "curator"}
MAX_DESC = 400

# Patrones del protocolo section 5: nombre candidato a timeout.
TIMEOUT = re.compile(r"timeout|ttl|expir|deadline|linger|keepalive|keep-alive", re.I)
# "wait" e "interval" solo si la descripcion confirma semantica temporal.
TEMPORAL_DUDOSO = re.compile(r"\bwait\b|interval|delay|period", re.I)
CONFIRMA_TIEMPO = re.compile(r"\b(ms|millis|milliseconds?|seconds?|minutes?|time)\b", re.I)

# Exclusiones explicitas (no-timeouts que el nombre podria confundir).
EXCLUIR_NOMBRE = re.compile(
    r"retries|retry\.?count|attempts|enabled?$|^use|policy$|class$|factory$|percent"
    r"|consumers?$|concurrent|threads?$|size$|count$", re.I)

# Casos limite del protocolo 2.bis: no son esperas de una operacion sino tareas
# periodicas, retencion o cache. Se registran marcados para revision humana.
LIMITROFE_NOMBRE = re.compile(r"cache|token|retention|retain|archive|scheduled|checker|recovery", re.I)
# En la descripcion solo cuentan las palabras que no aparecen por referencia cruzada
# a otro parametro (evita marcar requestTimeout porque menciona su "checker").
LIMITROFE_DESC = re.compile(r"cache|retention|retain|archive", re.I)


def limpiar(s: str, tope: int = MAX_DESC) -> str:
    t = re.sub(r"<[^>]+>", " ", s)
    t = H.unescape(t).replace("​", "").replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > tope:
        corte = t.rfind(" ", 0, tope)
        t = t[: corte if corte > 0 else tope].rstrip(" ,;.") + " [...]"
    return t


def tablas(texto: str):
    for tb in re.findall(r"<table.*?</table>", texto, re.S):
        filas = re.findall(r"<tr.*?</tr>", tb, re.S)
        if not filas:
            continue
        cabecera = [limpiar(c, 60) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", filas[0], re.S)]
        cuerpo = []
        for fila in filas[1:]:
            cuerpo.append([limpiar(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", fila, re.S)])
        yield cabecera, cuerpo


def leer(rel: str) -> str:
    ruta = RAW / rel
    if not ruta.exists():
        print(f"AVISO: falta evidencia {rel}", file=sys.stderr)
        return ""
    return ruta.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- separar unidad
UNIDAD_SUFIJO = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(ms|millis|milliseconds?|s|sec|seconds?|min|minutes?|h|hours?)$", re.I)
NORMALIZA_UNIDAD = {
    "millis": "ms", "millisecond": "ms", "milliseconds": "ms", "ms": "ms",
    "s": "s", "sec": "s", "second": "s", "seconds": "s",
    "min": "min", "minute": "min", "minutes": "min",
    "h": "h", "hour": "h", "hours": "h",
}


SOLO_NUMERO = re.compile(r"^-?\d+(?:\.\d+)?$")

# La unidad solo se acepta si la doc la declara sin ambiguedad: sufijo en el valor,
# sufijo en el nombre del parametro, o una frase explicita en la descripcion.
# Mencionar "seconds" de pasada NO basta: preferimos dejar la unidad vacia y marcar
# la fila antes que inferir mal (una unidad equivocada corrompe valor_ms).
UNIDAD_NOMBRE = [
    (re.compile(r"Ms$|MS$|\.ms$|[Mm]illis"), "ms"),
    (re.compile(r"Seconds$|Secs?$|\.seconds$"), "s"),
    (re.compile(r"Minutes$|Mins?$|\.minutes$"), "min"),
]
UNIDAD_DESCRIPCION = [
    (re.compile(r"in milli\s?seconds|in millis\b|value is in milli|\(in ms\)|\bmilliseconds\b", re.I), "ms"),
    (re.compile(r"in seconds|value is in seconds|number of seconds|seconds the|timeout of \d+ seconds?|\bsecond[s]? (?:before|to wait)\b", re.I), "s"),
    (re.compile(r"in minutes|number of minutes", re.I), "min"),
]


def separar_unidad(valor: str, nombre: str, descripcion: str):
    """Devuelve (valor_limpio, unidad). Unidad vacia = la doc no la declara."""
    v = valor.strip().strip("`")
    m = UNIDAD_SUFIJO.match(v)
    if m:
        return m.group(1), NORMALIZA_UNIDAD[m.group(2).lower()]

    for patron, unidad in UNIDAD_NOMBRE:
        if patron.search(nombre):
            return v, unidad
    for patron, unidad in UNIDAD_DESCRIPCION:
        if patron.search(descripcion):
            return v, unidad
    return v, ""


PALABRA_ESPECIAL = re.compile(r"^(infinite|disabled|none|null|unlimited|forever)$", re.I)


def sanear_valor(valor: str):
    """El default debe ser un numero o una palabra reservada reconocida. Si la doc
    pone una frase ("el valor de X se usa por defecto"), no hay valor citable:
    se devuelve NO_ENCONTRADO y la frase se conserva en notas."""
    v = valor.strip().strip("`").rstrip(".")
    if not v:
        return "NO_ENCONTRADO", "la doc no declara valor por defecto"
    if SOLO_NUMERO.match(v) or PALABRA_ESPECIAL.match(v):
        return v, ""
    numero = re.match(r"^(-?\d+(?:\.\d+)?)\b", v)
    if numero:      # p. ej. "0, which means that this feature is disabled"
        return numero.group(1), f"texto literal en la doc: \"{limpiar(v, 120)}\""
    return "NO_ENCONTRADO", f"la doc no declara un numero: \"{limpiar(v, 120)}\""


ESPECIALES = re.compile(r"^(infinite|disabled|none|null|false|true|)$", re.I)


def es_especial(valor: str) -> bool:
    v = valor.strip()
    if ESPECIALES.match(v):
        return True
    try:
        return float(v) <= 0
    except ValueError:
        return True  # valor relativo o no numerico: no entra a distribuciones


# ------------------------------------------------------ propuesta de tipo_timeout
REGLAS_TIPO = [
    ("SESSION", r"session"),
    ("HEARTBEAT_KEEPALIVE", r"heartbeat|keep\s?alive|keepalive|ping"),
    ("LEASE_ELECTION", r"lease|election|leader|quorum|discovery"),
    ("SHUTDOWN", r"shutdown|close|stop|drain|linger"),
    ("RETRY_BACKOFF", r"backoff|reconnect|retry"),
    ("IDLE", r"idle|inactiv"),
    ("CONNECT", r"connect(?!ion\s?request)|handshake"),
    ("READ_SOCKET", r"\bread\b|\bsocket\b|so_?timeout|receive"),
    ("REQUEST_RPC", r"request|invocation|\brpc\b|call|response|reply|exchange|send"),
]

# En la descripcion, "connection" aparece en cualquier parrafo; solo cuenta como
# CONNECT si el texto habla de *establecer* la conexion.
REGLAS_DESCRIPCION = [
    (tipo, r"establish|opening a connection|connect to\b" if tipo == "CONNECT" else patron)
    for tipo, patron in REGLAS_TIPO
]


def proponer_tipo(nombre: str, descripcion: str) -> str:
    """Primero se intenta con el nombre del parametro (mas fiable) y solo si no
    resuelve se recurre a la descripcion. Sigue siendo una PROPUESTA."""
    for tipo, patron in REGLAS_TIPO:
        if re.search(patron, nombre, re.I):
            return tipo
    for tipo, patron in REGLAS_DESCRIPCION:
        if re.search(patron, descripcion, re.I):
            return tipo
    return "OTRO"


BOOLEANO = re.compile(r"^(true|false)$", re.I)


def candidato(nombre: str, descripcion: str, valor: str = "") -> bool:
    if EXCLUIR_NOMBRE.search(nombre):
        return False
    if BOOLEANO.match(valor.strip()):
        return False          # interruptor, no limite temporal
    if TIMEOUT.search(nombre):
        return True
    if TEMPORAL_DUDOSO.search(nombre) and CONFIRMA_TIEMPO.search(descripcion):
        return True
    return False


# ------------------------------------------------------------------- extractores
def extraer_activemq():
    paginas = [
        ("tcp-transport-reference.html", "https://activemq.apache.org/components/classic/documentation/tcp-transport-reference"),
        ("failover-transport-reference.html", "https://activemq.apache.org/components/classic/documentation/failover-transport-reference"),
        ("connection-configuration-uri.html", "https://activemq.apache.org/components/classic/documentation/connection-configuration-uri"),
        ("discovery-transport-reference.html", "https://activemq.apache.org/components/classic/documentation/discovery-transport-reference"),
    ]
    for archivo, url in paginas:
        doc = leer(f"activemq/{archivo}")
        for cabecera, cuerpo in tablas(doc):
            if not (cabecera[:2] == ["Option Name", "Default Value"]):
                continue
            for celdas in cuerpo:
                if len(celdas) < 3:
                    continue
                nombre, valor, desc = celdas[0], celdas[1], celdas[2]
                if not candidato(nombre, desc, valor):
                    continue
                yield "activemq", "Classic (documentation, consultada 2026-08-08)", nombre, valor, desc, url


def extraer_dubbo():
    url = "https://dubbo.apache.org/en/docs3-v2/java-sdk/reference-manual/config/properties/"
    doc = leer("dubbo/config-properties.html")
    for cabecera, cuerpo in tablas(doc):
        if "Attribute" not in cabecera[:1] or "Default" not in cabecera:
            continue
        i_def = cabecera.index("Default")
        for celdas in cuerpo:
            if len(celdas) <= i_def + 2:
                continue
            nombre = celdas[1] or celdas[0]          # preferimos la clave de config (URL parameter)
            valor = celdas[i_def]
            desc = celdas[i_def + 2]
            if not nombre or not candidato(nombre, desc, valor):
                continue
            yield "dubbo", "3.x (docs3-v2, reference manual)", nombre, valor, desc, url


def extraer_camel():
    componentes = [
        ("http-component-4.18.html", "https://camel.apache.org/components/4.18.x/http-component.html"),
        ("jms-component-4.18.html", "https://camel.apache.org/components/4.18.x/jms-component.html"),
        ("netty-component-4.18.html", "https://camel.apache.org/components/4.18.x/netty-component.html"),
    ]
    vistos = set()
    for archivo, url in componentes:
        doc = leer(f"camel/{archivo}")
        for cabecera, cuerpo in tablas(doc):
            if cabecera[:2] != ["Name", "Description"] or "Default" not in cabecera:
                continue
            i_def = cabecera.index("Default")
            for celdas in cuerpo:
                if len(celdas) <= i_def:
                    continue
                nombre_bruto, desc, valor = celdas[0], celdas[1], celdas[i_def]
                # Spring Boot duplica cada opcion como camel.component.<x>.<opcion>
                if nombre_bruto.startswith("camel."):
                    continue
                # "connectTimeout (producer)" -> connectTimeout ; se guarda el ambito en notas
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:\(([^)]*)\))?", nombre_bruto)
                if not m:
                    continue
                nombre, ambito = m.group(1), (m.group(2) or "")
                if not candidato(nombre, desc, valor):
                    continue
                clave = (url, nombre)
                if clave in vistos:      # la misma opcion aparece en varias tablas de la pagina
                    continue
                vistos.add(clave)
                nota = f"componente camel-{Path(archivo).name.split('-')[0]}; ambito: {ambito}" if ambito else \
                       f"componente camel-{Path(archivo).name.split('-')[0]}"
                yield "camel", "4.18.x", nombre, valor, desc, url, nota

    # Default global de apagado ordenado: declarado en prosa en el manual.
    doc = leer("camel/graceful-shutdown.html")
    if re.search(r"timeout of 45 seconds", doc):
        yield ("camel", "4.18.x (manual)", "ShutdownStrategy.timeout", "45",
               "Graceful shutdown: let pending and current in flight exchanges run to completion "
               "before shutting down using a timeout of 45 seconds (can be configured), which then "
               "forces a hard shutdown.",
               "https://camel.apache.org/manual/graceful-shutdown.html",
               "valor declarado en prosa, no en tabla; unidad segundos explicita en el texto")


DEFAULT_JAVADOC = re.compile(r"The default is ([^.]{1,60})\.", re.I)


def extraer_curator():
    paginas = [
        ("CuratorFrameworkFactory.Builder.html",
         "https://curator.apache.org/apidocs/org/apache/curator/framework/CuratorFrameworkFactory.Builder.html"),
        ("CuratorFrameworkFactory.html",
         "https://curator.apache.org/apidocs/org/apache/curator/framework/CuratorFrameworkFactory.html"),
    ]
    vistos = set()
    for archivo, url in paginas:
        doc = leer(f"curator/{archivo}")
        # Cada metodo del javadoc: <section class="detail" id="nombre(...)"> ... </section>
        for m in re.finditer(r'<section class="detail" id="([A-Za-z0-9_]+)\(', doc):
            nombre = m.group(1)
            bloque = doc[m.start(): m.start() + 4000]
            texto = limpiar(bloque, 4000)
            if not candidato(nombre, texto):  # el javadoc no trae valor en tabla
                continue
            declarado = DEFAULT_JAVADOC.search(texto)
            if not declarado:
                continue     # la doc no publica el valor: no se inventa
            valor = declarado.group(1).strip()
            if nombre in vistos:
                continue
            vistos.add(nombre)
            yield ("curator", "5.9.1-SNAPSHOT (apidocs)", nombre, valor,
                   limpiar(texto.split("Parameters:")[0], MAX_DESC), url,
                   "default declarado en el javadoc del metodo del builder")


def main() -> int:
    dry = "--dry-run" in sys.argv

    with open(DATASET, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas = list(lector.fieldnames)
        existentes = list(lector)

    previas = sum(1 for r in existentes if r["proyecto"] in PROYECTOS)
    existentes = [r for r in existentes if r["proyecto"] not in PROYECTOS]
    siguiente = max((int(r["id"]) for r in existentes), default=0)

    nuevas, sin_unidad, sin_valor, duplicados = [], [], [], []
    indice = {}
    for registro in list(extraer_activemq()) + list(extraer_dubbo()) + list(extraer_camel()) + list(extraer_curator()):
        proyecto, version, nombre, valor, desc, url = registro[:6]
        nota_extra = registro[6] if len(registro) > 6 else ""

        nombre = nombre.strip()
        if not nombre or nombre.startswith("."):
            continue      # celda de tabla mal formada en la doc

        # Unidad de analisis: un parametro por proyecto = una fila. Si la doc lo
        # repite en varias tablas/paginas, se anota en lugar de duplicar la fila.
        clave = (proyecto, nombre)
        if clave in indice:
            fila = indice[clave]
            duplicados.append(f"{proyecto}/{nombre}")
            if "documentado en mas de un lugar" not in fila["notas"]:
                fila["notas"] = (fila["notas"] + "; " if fila["notas"] else "") + \
                    "documentado en mas de un lugar de la doc (se conserva la primera aparicion)"
            continue

        vnum, unidad = separar_unidad(valor, nombre, desc)
        vnum, nota_valor = sanear_valor(vnum)
        especial = es_especial(vnum)
        limitrofe = bool(LIMITROFE_NOMBRE.search(nombre) or LIMITROFE_DESC.search(desc))
        tipo = "OTRO" if limitrofe else proponer_tipo(nombre, desc)

        notas = [n for n in (nota_extra, nota_valor) if n]
        if limitrofe:
            notas.append("REVISAR_ALCANCE: periodico/retencion/cache (protocolo 2.bis)")
        elif tipo == "OTRO":
            notas.append("revisar categoria (propuesta automatica no concluyente)")
        if not unidad and vnum != "NO_ENCONTRADO" and not PALABRA_ESPECIAL.match(vnum):
            notas.append("unidad no declarada en la doc: pendiente de decision humana")
            sin_unidad.append(f"{proyecto}/{nombre}")
        if vnum == "NO_ENCONTRADO":
            sin_valor.append(f"{proyecto}/{nombre}")

        siguiente += 1
        fila = {
            "id": siguiente,
            "proyecto": proyecto,
            "version_doc": version,
            "parametro": nombre,
            "valor_original": vnum,
            "unidad_original": unidad,
            "valor_ms": "",
            "es_valor_especial": "true" if especial else "false",
            "tipo_timeout": tipo,
            "descripcion_oficial": desc,
            "fuente_url": url,
            "notas": "; ".join(notas),
        }
        indice[clave] = fila
        nuevas.append(fila)

    print(f"Filas previas de estos proyectos (reemplazadas): {previas}")
    print(f"Filas nuevas: {len(nuevas)} | por proyecto: {dict(Counter(r['proyecto'] for r in nuevas))}")
    print(f"por tipo: {dict(Counter(r['tipo_timeout'] for r in nuevas))}")
    print(f"especiales: {sum(1 for r in nuevas if r['es_valor_especial'] == 'true')}"
          f" | sin unidad declarada: {len(sin_unidad)}"
          f" | sin valor en la doc: {len(sin_valor)}"
          f" | duplicados fusionados: {len(duplicados)}")
    print(f"TOTAL dataset: {len(existentes) + len(nuevas)}")
    for etiqueta, lista in (("sin unidad", sin_unidad), ("sin valor", sin_valor), ("duplicados", duplicados)):
        if lista:
            print(f"  {etiqueta}: " + ", ".join(lista[:10]) + (" ..." if len(lista) > 10 else ""))

    if dry:
        print("(--dry-run: no se escribio el dataset)")
        for r in nuevas[:8]:
            print(f"  {r['proyecto']:<9} {r['parametro']:<34} {r['valor_original']:>8} {r['unidad_original']:<3} {r['tipo_timeout']}")
        return 0

    shutil.copy2(DATASET, str(DATASET) + ".bak")
    with open(DATASET, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(existentes + nuevas)
    print(f"Escrito {DATASET.name} (respaldo en {DATASET.name}.bak)")
    print("Siguiente: python scripts/normalizar.py datos/dataset_timeouts.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
