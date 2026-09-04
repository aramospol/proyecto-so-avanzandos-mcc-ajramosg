#!/usr/bin/env python3
"""Vuelca en `datos/justificaciones.csv` el resultado del rastreo de RQ3/RQ4.

Cada etiqueta de aqui sale de haber abierto la incidencia y leido el texto que se
cita en `justificacion_texto_resumen`; la evidencia cruda esta en
`datos/raw/justificaciones/`. Las filas sin hallazgo se marcan NO_ENCONTRADO con
`donde_busque` completo, que es lo que exige el protocolo: la ausencia de
justificacion es un resultado, no un hueco.

TODAS las etiquetas quedan como PRELIMINAR en `notas`. La decision final es
del estudiante, que debe abrir cada URL antes de validarla.

Uso:  python scripts/registrar_justificaciones.py
"""

import csv
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
MUESTRA = RAIZ / "datos" / "justificaciones.csv"
FECHA = "2026-08-20"

BUSQUEDA_JIRA = ('(1) JIRA de ASF, frase exacta del parametro '
                 '(JQL text ~ "<parametro>" ORDER BY created ASC), abriendo las tres '
                 'incidencias mas antiguas; (2) historia de commits del repositorio '
                 'oficial (API de busqueda de GitHub por el nombre del parametro). '
                 'Evidencia cruda en datos/raw/justificaciones/. No se reviso la lista '
                 'de correo ni el git blame linea a linea del archivo de defaults.')

# Hallazgos con cita leida. clave = (proyecto, parametro).
HALLAZGOS = {
    ("kafka", "zookeeper.session.timeout.ms"): dict(
        resumen="KIP-537 sube el default de 6 a 18 s razonando el cambio de entorno: el "
                "valor viejo servia para centros de datos controlados, pero en nubes "
                "inestables produce expiraciones espurias. Justifica el sentido del cambio "
                "por experiencia operativa, no con mediciones, y no explica por que 18.",
        tipo="HEURISTICA",
        url="https://cwiki.apache.org/confluence/display/KAFKA/KIP-537%3A+Increase+default+zookeeper+session+timeout",
        nota="PRELIMINAR. Cita: 'The tradeoff with a larger session timeout is that it "
             "allows the system to smooth over transient instability at the cost of slower "
             "detection of genuine failures. Based on our experience, genuine failures are "
             "rare...'. Implementado en KAFKA-9102 "
             "(https://issues.apache.org/jira/browse/KAFKA-9102), commit 4bde9bb3."),

    ("cassandra", "slow_query_log_timeout"): dict(
        resumen='El autor sube el default de 200 a 500 ms y lo explica sin medicion: '
                '"I know this is very high but I prefer to be on the safe side".',
        tipo="HEURISTICA",
        url="https://issues.apache.org/jira/browse/CASSANDRA-12403",
        nota="Comentario de 2016-08-10 en el hilo que introduce la deteccion de "
             "consultas lentas. Razonamiento explicito, sin datos que lo respalden."),

    ("hdfs", "dfs.client.datanode-restart.timeout"): dict(
        resumen="La incidencia que introduce el parametro declara el default de 30 s "
                "sin dar ninguna razon del numero.",
        tipo="ARBITRARIO",
        url="https://issues.apache.org/jira/browse/HDFS-5924",
        nota="Comentario de 2014-02-25: 'By default dfs.client.datanode-restart.timeout "
             "is 30 seconds'. RQ4: HDFS-13889 documenta que escribirlo como '30s' rompe "
             "la compatibilidad entre clientes Hadoop 3 y clusteres Hadoop 2 "
             "(NumberFormatException)."),

    ("yarn", "yarn.log-aggregation-status.time-out.ms"): dict(
        resumen="El valor solo aparece en una revision de consistencia de yarn-default.xml, "
                "que corrige la documentacion sin justificar el numero.",
        tipo="ARBITRARIO",
        url="https://issues.apache.org/jira/browse/YARN-3069",
        nota="Comentario de 2015-06-16: 'The default value is 600000, not 60000'. "
             "RQ4: la incidencia existe porque la documentacion contradecia al codigo."),

    ("yarn", "yarn.nodemanager.linux-container-executor.cgroups.delete-timeout-ms"): dict(
        resumen="Aparece en la misma revision de yarn-default.xml; un revisor opina que "
                "el numero de reintentos asociado es alto, sin datos ni decision.",
        tipo="ARBITRARIO",
        url="https://issues.apache.org/jira/browse/YARN-3069",
        nota="Comentario de 2015-05-15: 'Default value is 2000, 500. (I'm thinking the "
             "default number of retries is too high.)'"),

    ("tomcat", "selectorTimeout"): dict(
        resumen="El commit que fija el default en la doc (1000 ms) solo lo declara; ni el "
                "mensaje ni el cambio dan una razon del numero.",
        tipo="ARBITRARIO",
        url="https://github.com/apache/tomcat/commit/c9772ad6",
        nota="Commit de 2007-05-18. El valor ya existia en el codigo; no se localizo el "
             "commit que lo introdujo.",
        donde="Bugzilla de ASF (su API exige login); busqueda de commits en apache/tomcat; "
              "doc oficial del conector HTTP"),

    ("tomcat", "socket.soTimeout"): dict(
        resumen="El valor no es propio: la doc declara que equivale a connectionTimeout, y "
                "un commit posterior renombra soTimeout a connectionTimeout por consistencia.",
        tipo="HERENCIA",
        url="https://github.com/apache/tomcat/commit/712bcbcf",
        nota="Commit de 2016-10-31.",
        donde="Bugzilla de ASF (su API exige login); busqueda de commits en apache/tomcat; "
              "doc oficial del conector HTTP"),
}

# Incidencias utiles para RQ4 aunque no justifiquen el valor (problemas causados por
# la configuracion). Se anotan en la fila sin cambiar su tipo_justificacion.
RQ4 = {
    ("kafka", "retry.backoff.ms"):
        "RQ4: KAFKA-899 recomienda como remedio subir el default de 100 ms a 1000 ms "
        "(https://issues.apache.org/jira/browse/KAFKA-899).",
    ("kafka", "connections.max.idle.ms"):
        "RQ4: KAFKA-2078 atribuye fallos de cliente al cierre de conexiones ociosas a los "
        "10 minutos por defecto (https://issues.apache.org/jira/browse/KAFKA-2078).",
}


def main() -> int:
    with open(MUESTRA, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
        columnas = list(filas[0].keys())

    conteo = {}
    for fila in filas:
        clave = (fila["proyecto"], fila["parametro"])
        h = HALLAZGOS.get(clave)
        if h:
            fila["justificacion_texto_resumen"] = h["resumen"]
            fila["tipo_justificacion"] = h["tipo"]
            fila["justificacion_url"] = h["url"]
            fila["donde_busque"] = h.get("donde", BUSQUEDA_JIRA)
            fila["notas"] = "PRELIMINAR. " + h["nota"]
        elif fila["tipo_justificacion"] in ("PENDIENTE", ""):
            fila["justificacion_texto_resumen"] = "NO_ENCONTRADO"
            fila["tipo_justificacion"] = "NO_ENCONTRADO"
            fila["justificacion_url"] = "NO_ENCONTRADO"
            fila["donde_busque"] = BUSQUEDA_JIRA
            fila["notas"] = ("PRELIMINAR. Las incidencias que mencionan el parametro "
                             "lo usan o lo reportan, ninguna explica de donde sale el valor.")
        if clave in RQ4:
            fila["notas"] = (fila["notas"] + " " + RQ4[clave]).strip()
        fila["fecha_consulta"] = FECHA
        conteo[fila["tipo_justificacion"]] = conteo.get(fila["tipo_justificacion"], 0) + 1

    with open(MUESTRA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)

    print(f"Filas: {len(filas)}")
    for tipo, n in sorted(conteo.items(), key=lambda x: -x[1]):
        print(f"  {tipo:<16} {n:>3}  ({100 * n / len(filas):.0f} %)")
    print("\nTodas las etiquetas quedan como PRELIMINAR: revisar abriendo cada URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
