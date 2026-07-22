#!/usr/bin/env python3
"""Extractor (scraping) del dataset piloto: ZooKeeper, Kafka y Tomcat (semana 2).

Este es el script que se uso para hacer el scraping de la documentacion oficial.
Se conserva aqui por transparencia y reproducibilidad del metodo: muestra COMO se
obtuvieron los valores.

Metodo:
- Kafka: la funcion kafka_entries() PARSEA el HTML crudo descargado en
  datos/raw/kafka/*.html (fuente autoritativa); toma nombre, Default, unidad y
  descripcion tal como aparecen en la pagina, sin ejecutar el proyecto.
- ZooKeeper y Tomcat: valores transcritos de datos/raw/ tras verificacion manual
  contra el HTML descargado.

"""
import re, html as H, csv, os

RAW = "datos/raw"
FECHA = "2026-07-21"
rows = []
_id = 0

def add(proyecto, version, parametro, valor, unidad, tipo, desc, url, notas="", especial=None):
    global _id
    _id += 1
    v = str(valor).strip()
    if especial is None:
        especial = v.lower() in ("null", "none", "", "-1", "-2") or v == "0" or v == "9223372036854775807"
    rows.append({
        "id": _id, "proyecto": proyecto, "version_doc": version, "parametro": parametro,
        "valor_original": v if v else "NO_ENCONTRADO", "unidad_original": unidad, "valor_ms": "",
        "es_valor_especial": "true" if especial else "false", "tipo_timeout": tipo, "descripcion_oficial": desc,
        "fuente_url": url, "fecha_consulta": FECHA, "notas": notas,
    })

# ---------------------------------------------------------------- ZooKeeper
ZK = "https://zookeeper.apache.org/doc/current/zookeeperAdmin.html#sc_configuration"
zk = [
 ("tickTime","NO_ENCONTRADO","ms","HEARTBEAT_KEEPALIVE","Unidad base de tiempo; regula heartbeats y timeouts.","doc no fija default oficial; el ejemplo de config usa 2000 pero es ilustrativo",True),
 ("initLimit","NO_ENCONTRADO","ticks","LEASE_ELECTION","Tiempo (en ticks) para que followers conecten y sincronicen con el lider.","doc no fija default; ejemplo usa 5; unidad ticks -> pendiente normalizacion",True),
 ("syncLimit","NO_ENCONTRADO","ticks","LEASE_ELECTION","Tiempo (en ticks) para que followers sincronicen con el lider.","doc no fija default; ejemplo usa 2; unidad ticks",True),
 ("minSessionTimeout","2 x tickTime","ms","SESSION","Timeout minimo de sesion que el server permite negociar.","default relativo a tickTime; no numerico -> pendiente",True),
 ("maxSessionTimeout","20 x tickTime","ms","SESSION","Timeout maximo de sesion que el server permite negociar.","default relativo a tickTime; no numerico -> pendiente",True),
 ("cnxTimeout","5","s","LEASE_ELECTION","Timeout para abrir conexiones de notificaciones de eleccion de lider (electionAlg 3).","",False),
 ("quorumCnxnTimeoutMs","-1","ms","LEASE_ELECTION","Read timeout de conexiones de eleccion de lider; -1 usa syncLimit*tickTime.","especial: -1 => deriva de syncLimit*tickTime",True),
 ("connectToLearnerMasterLimit","initLimit","ticks","LEASE_ELECTION","Ticks para que followers conecten al lider tras la eleccion.","default relativo a initLimit; unidad ticks",True),
 ("maxTimeToWaitForEpoch","NO_ENCONTRADO","ms","LEASE_ELECTION","Tiempo maximo de espera de epoch de los voters al activar lider.","doc no fija default; sugiere ~2s en cross-DC",True),
 ("fsync.warningthresholdms","1000","ms","OTRO","Umbral para advertir si un fsync del WAL tarda mas de este valor.","monitoreo, no aborta operacion; REVISAR_ALCANCE",False),
 ("requestThrottleStallTime","100","ms","OTRO","Tiempo maximo que un hilo puede esperar a ser notificado para procesar una peticion.","control de admision; REVISAR clasificacion",False),
 ("zookeeper.request_throttler.shutdownTimeout","10000","ms","SHUTDOWN","Tiempo que RequestThrottler espera a drenar la cola en el apagado antes de forzarlo.","",False),
 ("multiAddress.reachabilityCheckTimeoutMs","1000","ms","CONNECT","Timeout del chequeo de alcanzabilidad (ICMP/TCP) de multiples direcciones.","solo si multiAddress.enabled=true",False),
 ("observer.reconnectDelayMs","0","ms","RETRY_BACKOFF","Espera del observer antes de reconectar tras perder al lider.","0 => sin espera (especial)",True),
 ("observer.election.DelayMs","200","ms","LEASE_ELECTION","Retrasa la participacion del observer en una eleccion tras desconexion.","",False),
 ("connectionFreezeTime","-1","ms","OTRO","Intervalo de ajuste de la probabilidad de descarte del throttler de conexiones.","-1 => throttling deshabilitado (especial); REVISAR_ALCANCE",True),
 ("connectionTokenFillTime","1","ms","OTRO","Intervalo de recarga del token bucket del throttler de conexiones.","rate limiting, no timeout de red; REVISAR_ALCANCE",False),
 ("flushDelay","0","ms","OTRO","Retraso del flush del commit log.","0 => deshabilitado (especial); REVISAR_ALCANCE",True),
 ("maxWriteQueuePollTime","flushDelay/3","ms","OTRO","Espera antes de hacer flush cuando no hay nuevas peticiones encoladas.","default relativo a flushDelay; deshabilitado si flushDelay=0",True),
 ("watcherCleanIntervalInSeconds","10","min","OTRO","Intervalo de limpieza de watchers muertos (WatchManagerOptimized).","doc dice '10 minutes'; nombre implica seg (600); periodico -> REVISAR_ALCANCE",False),
]
for p,v,u,t,d,n,e in zk:
    add("zookeeper","3.9",p,v,u,t,d,ZK,n,e)

# ---------------------------------------------------------------- Tomcat
TC = "https://tomcat.apache.org/tomcat-9.0-doc/config/http.html"
tc = [
 ("connectionTimeout","60000","ms","READ_SOCKET","Espera tras aceptar conexion hasta recibir la linea URI de la peticion.","-1 => infinito; ref config del server usa 60000",False),
 ("keepAliveTimeout","connectionTimeout","ms","IDLE","Espera de otra peticion HTTP antes de cerrar la conexion (keep-alive).","default = valor de connectionTimeout (relativo)",True),
 ("asyncTimeout","30000","ms","REQUEST_RPC","Timeout por defecto para peticiones asincronas (default Servlet spec).","",False),
 ("connectionUploadTimeout","300000","ms","READ_SOCKET","Timeout durante una subida de datos en progreso (si disableUploadTimeout=false).","",False),
 ("connectionLinger","-1","s","SHUTDOWN","Segundos de SO_LINGER de los sockets al cerrarse.","-1 => linger deshabilitado (especial)",True),
 ("socket.soLingerTime","NO_ENCONTRADO","s","SHUTDOWN","Opcion SO_LINGER del socket; equivalente a connectionLinger.","sin default propio; equivale a connectionLinger",True),
 ("socket.soTimeout","connectionTimeout","ms","READ_SOCKET","Equivalente al atributo estandar connectionTimeout.","sin default propio; equivale a connectionTimeout",True),
 ("selectorTimeout","1000","ms","IDLE","Timeout del select() del poller (NIO); limpieza de conexiones en el mismo hilo.","",False),
 ("socket.unlockTimeout","250","ms","SHUTDOWN","Timeout para desbloquear el socket acceptor al detener el connector.","",False),
 ("pollTime","2000","microsegundos","OTRO","Duracion de una llamada poll (APR); unidad en microsegundos.","unidad microsegundos -> normalizar.py la marcara pendiente",False),
 ("threadsMaxIdleTime","60000","ms","IDLE","Tiempo que los hilos siguen vivos si hay mas de minSpareThreads en el executor.","",False),
]
for p,v,u,t,d,n,e in tc:
    add("tomcat","9.0",p,v,u,t,d,TC,n,e)

# ---------------------------------------------------------------- Kafka (parse raw HTML)
def kafka_entries(path):
    h = open(path, encoding="utf-8", errors="ignore").read()
    out = {}
    for m in re.finditer(r'<h4><a id="([^"]+)"></a>[^<]*<a[^>]*>([^<]+)</a></h4>\s*<p>(.*?)</p>\s*<table>(.*?)</table>', h, flags=re.S):
        aid, name, desc, tbl = m.groups()
        d = re.search(r'Default:</th><td>(.*?)</td>', tbl, flags=re.S)
        default = H.unescape(re.sub(r'<[^>]+>', '', d.group(1)).strip()) if d else "NO_ENCONTRADO"
        default = re.sub(r'\s*\(.*?\)\s*$', '', default).strip()  # quita "(18 seconds)"
        desc = H.unescape(re.sub(r'<[^>]+>', '', desc)).strip()
        out.setdefault(name, (default, desc))
    return out

def unit_of(name):
    if name.endswith(".ms") or ".ms." in name or name.endswith("Ms"): return "ms"
    if name.endswith(".minutes") or name.endswith(".min"): return "min"
    if name.endswith(".hours"): return "h"
    if name.endswith(".seconds"): return "s"
    return "ms"

# tipo_timeout propuesto y (opcional) nota / flag alcance por parametro Kafka
BROKER = {
 "zookeeper.session.timeout.ms":("SESSION",""),
 "zookeeper.connection.timeout.ms":("CONNECT","null => usa zookeeper.session.timeout.ms"),
 "connections.max.idle.ms":("IDLE",""),
 "request.timeout.ms":("REQUEST_RPC","inter-broker"),
 "replica.socket.timeout.ms":("READ_SOCKET",""),
 "replica.fetch.wait.max.ms":("READ_SOCKET","max espera por fetch del follower"),
 "replica.lag.time.max.ms":("HEARTBEAT_KEEPALIVE","liveness ISR; REVISAR clasificacion"),
 "replica.fetch.backoff.ms":("RETRY_BACKOFF",""),
 "controller.socket.timeout.ms":("READ_SOCKET",""),
 "controller.quorum.election.timeout.ms":("LEASE_ELECTION",""),
 "controller.quorum.fetch.timeout.ms":("LEASE_ELECTION",""),
 "controller.quorum.election.backoff.max.ms":("RETRY_BACKOFF",""),
 "controller.quorum.request.timeout.ms":("REQUEST_RPC",""),
 "controller.quorum.retry.backoff.ms":("RETRY_BACKOFF",""),
 "controller.quorum.append.linger.ms":("OTRO","linger de batching; REVISAR"),
 "group.initial.rebalance.delay.ms":("LEASE_ELECTION","retraso de coordinacion de rebalanceo"),
 "group.min.session.timeout.ms":("SESSION",""),
 "group.max.session.timeout.ms":("SESSION",""),
 "group.consumer.session.timeout.ms":("SESSION",""),
 "group.consumer.min.session.timeout.ms":("SESSION",""),
 "group.consumer.max.session.timeout.ms":("SESSION",""),
 "group.consumer.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.consumer.min.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.consumer.max.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.share.session.timeout.ms":("SESSION",""),
 "group.share.min.session.timeout.ms":("SESSION",""),
 "group.share.max.session.timeout.ms":("SESSION",""),
 "group.share.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.share.min.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.share.max.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "group.share.record.lock.duration.ms":("LEASE_ELECTION","lock de adquisicion de registros"),
 "group.share.min.record.lock.duration.ms":("LEASE_ELECTION",""),
 "group.share.max.record.lock.duration.ms":("LEASE_ELECTION",""),
 "group.coordinator.append.linger.ms":("OTRO","linger de batching; REVISAR"),
 "transaction.max.timeout.ms":("REQUEST_RPC","vida maxima de transaccion; REVISAR"),
 "offsets.commit.timeout.ms":("REQUEST_RPC",""),
 "connections.max.reauth.ms":("SESSION","0 => deshabilitado"),
 "controlled.shutdown.retry.backoff.ms":("RETRY_BACKOFF","backoff dentro de apagado controlado"),
 "broker.heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE","KRaft"),
 "broker.session.timeout.ms":("SESSION","lease de broker en KRaft"),
 "initial.broker.registration.timeout.ms":("REQUEST_RPC","registro inicial en el quorum"),
 "remote.fetch.max.wait.ms":("READ_SOCKET","tiered storage"),
 "socket.connection.setup.timeout.ms":("CONNECT",""),
 "socket.connection.setup.timeout.max.ms":("CONNECT",""),
 "connection.failed.authentication.delay.ms":("OTRO","retraso de cierre tras fallo de auth"),
 "log.dir.failure.timeout.ms":("OTRO","deteccion de fallo de log dir"),
 "sasl.login.connect.timeout.ms":("CONNECT","OAUTHBEARER; null=sin timeout"),
 "sasl.login.read.timeout.ms":("READ_SOCKET","OAUTHBEARER; null=sin timeout"),
 "sasl.login.retry.backoff.ms":("RETRY_BACKOFF",""),
 "sasl.login.retry.backoff.max.ms":("RETRY_BACKOFF",""),
 "sasl.oauthbearer.jwks.endpoint.retry.backoff.ms":("RETRY_BACKOFF",""),
 "sasl.oauthbearer.jwks.endpoint.retry.backoff.max.ms":("RETRY_BACKOFF",""),
 "sasl.oauthbearer.jwks.endpoint.refresh.ms":("OTRO","intervalo refresco JWKS; REVISAR_ALCANCE"),
}
# limitrofes (periodico/retencion/lifecycle) -> REVISAR_ALCANCE (protocolo 2.bis)
BROKER_BORDER = {
 "log.flush.interval.ms","log.flush.offset.checkpoint.interval.ms","log.flush.scheduler.interval.ms",
 "log.flush.start.offset.checkpoint.interval.ms","log.retention.ms","log.retention.hours",
 "log.retention.minutes","log.retention.check.interval.ms","log.roll.ms","log.roll.jitter.ms",
 "log.segment.delete.delay.ms","log.cleaner.backoff.ms","log.cleaner.delete.retention.ms",
 "log.cleaner.min.compaction.lag.ms","log.cleaner.max.compaction.lag.ms","log.local.retention.ms",
 "metadata.log.segment.ms","metadata.log.max.snapshot.interval.ms","metadata.max.retention.ms",
 "metadata.max.idle.interval.ms","offsets.retention.minutes","offsets.retention.check.interval.ms",
 "replica.high.watermark.checkpoint.interval.ms","delegation.token.expiry.time.ms",
 "delegation.token.max.lifetime.ms","delegation.token.expiry.check.interval.ms","producer.id.expiration.ms",
 "transaction.abort.timed.out.transaction.cleanup.interval.ms","transactional.id.expiration.ms",
 "transaction.remove.expired.transaction.cleanup.interval.ms","remote.log.manager.task.interval.ms",
}
be = kafka_entries(f"{RAW}/kafka/kafka_config-3.9.html")
for name,(tipo,nota) in BROKER.items():
    if name in be:
        v,d = be[name]
        add("kafka","3.9",name,v,unit_of(name),tipo,d[:100],f"https://kafka.apache.org/documentation/#brokerconfigs_{name}","broker; "+nota if nota else "broker")
for name in sorted(BROKER_BORDER):
    if name in be:
        v,d = be[name]
        add("kafka","3.9",name,v,unit_of(name),"OTRO",d[:100],f"https://kafka.apache.org/documentation/#brokerconfigs_{name}","broker; REVISAR_ALCANCE: periodico/retencion (protocolo 2.bis)")

PROD = {
 "request.timeout.ms":("REQUEST_RPC",""),"delivery.timeout.ms":("REQUEST_RPC","cota extremo a extremo de send()"),
 "linger.ms":("OTRO","linger de batching; 0=sin espera"),"connections.max.idle.ms":("IDLE",""),
 "max.block.ms":("OTRO","bloqueo de send()/metadata/buffer"),"transaction.timeout.ms":("REQUEST_RPC",""),
 "socket.connection.setup.timeout.ms":("CONNECT",""),"socket.connection.setup.timeout.max.ms":("CONNECT",""),
 "reconnect.backoff.ms":("RETRY_BACKOFF",""),"reconnect.backoff.max.ms":("RETRY_BACKOFF",""),
 "retry.backoff.ms":("RETRY_BACKOFF",""),"retry.backoff.max.ms":("RETRY_BACKOFF",""),
 "partitioner.availability.timeout.ms":("OTRO","0=deshabilitado"),
 "metadata.max.age.ms":("OTRO","refresco de metadata; REVISAR_ALCANCE"),
 "metadata.max.idle.ms":("IDLE","cache de metadata ociosa"),
}
pe = kafka_entries(f"{RAW}/kafka/producer_config-3.9.html")
for name,(tipo,nota) in PROD.items():
    if name in pe:
        v,d = pe[name]
        add("kafka","3.9",name,v,unit_of(name),tipo,d[:100],f"https://kafka.apache.org/documentation/#producerconfigs_{name}","producer; "+nota if nota else "producer")

CONS = {
 "session.timeout.ms":("SESSION",""),"heartbeat.interval.ms":("HEARTBEAT_KEEPALIVE",""),
 "request.timeout.ms":("REQUEST_RPC",""),"default.api.timeout.ms":("REQUEST_RPC","default de APIs cliente"),
 "max.poll.interval.ms":("SESSION","liveness por poll(); REVISAR"),"fetch.max.wait.ms":("READ_SOCKET",""),
 "connections.max.idle.ms":("IDLE",""),"socket.connection.setup.timeout.ms":("CONNECT",""),
 "socket.connection.setup.timeout.max.ms":("CONNECT",""),"reconnect.backoff.ms":("RETRY_BACKOFF",""),
 "reconnect.backoff.max.ms":("RETRY_BACKOFF",""),"retry.backoff.ms":("RETRY_BACKOFF",""),
 "retry.backoff.max.ms":("RETRY_BACKOFF",""),"metadata.max.age.ms":("OTRO","refresco metadata; REVISAR_ALCANCE"),
 "auto.commit.interval.ms":("OTRO","commit periodico; REVISAR_ALCANCE"),
}
ce = kafka_entries(f"{RAW}/kafka/consumer_config-3.9.html")
for name,(tipo,nota) in CONS.items():
    if name in ce:
        v,d = ce[name]
        add("kafka","3.9",name,v,unit_of(name),tipo,d[:100],f"https://kafka.apache.org/documentation/#consumerconfigs_{name}","consumer; "+nota if nota else "consumer")

cols = ["id","proyecto","version_doc","parametro","valor_original","unidad_original","valor_ms",
        "es_valor_especial","tipo_timeout","clasificado_por","descripcion_oficial","fuente_url","fecha_consulta","notas"]
with open("datos/dataset_timeouts.csv","w",newline="",encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader(); w.writerows(rows)

from collections import Counter
print("Total filas:", len(rows))
print("Por proyecto:", dict(Counter(r["proyecto"] for r in rows)))
print("Por tipo:", dict(Counter(r["tipo_timeout"] for r in rows)))
print("Especiales:", sum(1 for r in rows if r["es_valor_especial"]=="true"))
print("REVISAR_ALCANCE:", sum(1 for r in rows if "REVISAR_ALCANCE" in r["notas"]))
