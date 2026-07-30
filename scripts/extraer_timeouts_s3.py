#!/usr/bin/env python3
"""Semana 3: extrae timeouts de HDFS, YARN, HBase y Cassandra del HTML/XML crudo
en datos/raw/ y los ANEXA a datos/dataset_timeouts.csv.

- EXCLUYE no-timeouts (contadores de reintentos, booleanos, factores, specs).
- Marca REVISAR_ALCANCE los periodicos/retencion/cache/metricas (protocolo 2.bis).
- tipo_timeout es una PROPUESTA gruesa por reglas de palabra clave; revision humana.
Valores tomados literalmente del crudo; unidad separada del valor.
"""
import re, html as H, csv
RAW="datos/raw"; FECHA="2026-07-29"
def clean(s): return re.sub(r'\s+',' ',H.unescape(re.sub(r'<[^>]+>',' ',s))).strip()

# ---------- parsers (identicos al dump) ----------
def hadoop(path):
    t=open(path,encoding='utf-8',errors='ignore').read(); out=[]
    for m in re.finditer(r'<property>(.*?)</property>',t,re.S):
        b=m.group(1); n=re.search(r'<name>(.*?)</name>',b,re.S)
        v=re.search(r'<value>(.*?)</value>',b,re.S); d=re.search(r'<description>(.*?)</description>',b,re.S)
        if not n: continue
        out.append((clean(n.group(1)), clean(v.group(1)) if v else "", clean(d.group(1)) if d else ""))
    return out
def hbase(path):
    t=open(path,encoding='utf-8',errors='ignore').read(); out=[]
    for m in re.finditer(r'<div id="([^"]+)" class="dlist">(.*?)</dl>\s*</div>',t,re.S):
        name=m.group(1); b=m.group(2)
        if not re.match(r'^[a-zA-Z0-9._-]+$',name): continue
        de=re.search(r'Description</div>\s*<p>(.*?)</p>',b,re.S)
        df=re.search(r'Default</div>\s*<p>(?:<code>)?(.*?)(?:</code>)?</p>',b,re.S)
        out.append((name, clean(df.group(1)) if df else "", clean(de.group(1)) if de else ""))
    return out
def cassandra(path):
    t=open(path,encoding='utf-8',errors='ignore').read(); out=[]
    for m in re.finditer(r'<h2 id="([^"]+)"><a[^>]*></a><code>([^<]+)</code></h2>(.*?)(?=<h2 id=|</article>|<footer)',t,re.S):
        name=m.group(2).strip(); b=m.group(3)
        df=re.search(r'Default Value:</em>\s*(.*?)</p>',b,re.S)
        de=re.search(r'<p>(.*?)</p>',b,re.S)
        out.append((name, clean(df.group(1)) if df else "NO_ENCONTRADO", clean(de.group(1)) if de else ""))
    return out

TIMEOUT=re.compile(r'(timeout|time-out|expir|\bttl\b|deadline|backoff|retry|retries|idle|keepalive|keep-alive|lease|heartbeat|heart-beat|session|linger|\.wait|delay|\.period|liveness|elapse|expire|recheck|drain|graceful|decommission)',re.I)

def is_excluded(name,val,desc):
    v=val.strip().lower()
    if v in ("true","false"): return "booleano"
    if re.match(r'^\d+\.\d+f?$',v): return "factor/float"
    if re.match(r'^-?\d+(,\d+)+$',v): return "multi-valor/spec"
    if v.startswith("${"): return "referencia a otra prop"
    nl=name.lower()
    if re.search(r'retries$|retries\.on|(retries?|retry)[._-]?(number|attempts|times|max)|max[._-]?retries|num-retries|failover-retries|cached\.conn\.retry|block\.write\.retries|max\.attempts|max-attempts|retry-attempts|zk\.retries|bulkload\.retries|retry\.times',nl):
        return "contador de reintentos (no duracion)"
    if re.search(r'per\.interval|per\.heartbeat\.check|tracked\.nodes|periods\.before|scanned\.per|concurrent\.',nl):
        return "contador/tamano (no duracion)"
    if nl.endswith(("enable","enabled","allowed")) or "scaling-enable" in nl or nl.endswith("factor"): return "toggle/factor"
    if "heap.percent" in nl or "per.am.heartbeat" in nl or "pending.limit" in nl or "pending.blocks.per.lock" in nl or "max.full.block.report.leases" in nl: return "contador/tamano"
    if nl in ("internode_timeout","rpc_keepalive","inter_dc_tcp_nodelay","repair_session_space") or "tcpnodelay" in nl or "tcp_nodelay" in nl: return "toggle/no-duracion"
    if nl.endswith("retry.policy.spec"): return "spec de politica"
    return None

BORDER=re.compile(r'(\.period\b|\.period\.|logroll|log-roll|checkpoint|metrics\.logger|\.ttl\b|\.ttl-|\bttl\b|cache.*expir|expir.*cache|scan\.period|cleaner\.?period|balancer\.period|mob\..*period|initial.?delay|initialdelay|startup\.delay\.block|sharedcache|federation\.cache|activities-manager|timeline-service\.ttl|leveldb.*ttl|key\.provider\.cache|ugi\.expire|mmap\.cache|shortcircuit\.streams\.cache|server-defaults\.validity|retrycache\.expiry|replica\.cache\.expiry|socketcache\.expiry|streaming_state_expires|cache_load|recheck-interval|tail-edits\.period|scan\.period\.hours|timer\.period|derive\.cache\.period|periodic\.roll|internode_tcp_user_timeout|internode_streaming|slow_query_log|deadnode\.detection\.idle\.sleep|debug-delay|delete\.debug|revocation\.timeout|unregister-delay|internal-timers-ttl|drain-entities|app-collector\.linger|delete-delay|delete-timeout|cgroups)',re.I)

def tipo_of(name,desc):
    n=name.lower(); s=(name+" "+desc).lower()
    # semantica explicita primero
    if 'session' in n and 'space' not in n: return "SESSION"
    if 'lease' in n or 'elect' in s: return "LEASE_ELECTION"
    if 'liveness' in s or ('expir' in n and any(k in n for k in ('node','container','master','.am.','nm.'))): return "SESSION"
    if 'heartbeat' in s or 'heart-beat' in s: return "HEARTBEAT_KEEPALIVE"
    if 'backoff' in n: return "RETRY_BACKOFF"
    if 'retry' in n and ('interval' in n or 'window' in n or 'sleep' in s): return "RETRY_BACKOFF"
    if any(k in s for k in ('graceful','decommission','shutdown','sigkill','drain')) or 'restart' in n: return "SHUTDOWN"
    if 'idle' in n: return "IDLE"
    # RPC/peticion ANTES que connect/read (la desc suele mencionar 'connection')
    if 'rpc' in n or 'operation.timeout' in n or 'request' in n or 'quorum' in n or n.startswith('dfs.qj'): return "REQUEST_RPC"
    # connect/read guiados por el NOMBRE, no la descripcion
    if 'connect' in n: return "CONNECT"
    if 'read' in n or 'write' in n or 'socket' in n: return "READ_SOCKET"
    return "OTRO"

SUF={'ms':'ms','millis':'ms','msec':'ms','s':'s','sec':'s','secs':'s','m':'min','min':'min','mins':'min','h':'h','hours':'h','d':'d','days':'d'}
def split_unit(val,name,desc):
    v=val.strip()
    m=re.match(r'^(\d+(?:\.\d+)?)\s*(ms|millis|msec|secs?|mins?|hours?|days?|[smhd])$',v,re.I)
    if m: return m.group(1), SUF[m.group(2).lower()]
    if not re.match(r'^\d+$',v): return v, ""  # no numerico -> sin unidad (normalizar lo marca)
    nl=name.lower()
    if nl.endswith(('.ms','-ms','.millis','msec')) or nl.endswith('millis') or 'timeout.ms' in nl or nl.endswith('-ms'): return v,'ms'
    if nl.endswith(('-sec','-secs','.sec','.seconds','_secs','timeout-sec','secs')) or nl.endswith('seconds'): return v,'s'
    if nl.endswith(('-mins','.minutes','-min')) or nl.endswith('minutes') or 'delay-mins' in nl or 'period-mins' in nl: return v,'min'
    if nl.endswith(('.hours','-hours')) or 'period.hours' in nl: return v,'h'
    dl=desc.lower()
    if 'millisecond' in dl or ' in ms' in dl or '(ms' in dl or 'msec' in dl: return v,'ms'
    if 'in seconds' in dl or 'second' in dl: return v,'s'
    if 'in minutes' in dl or 'minute' in dl: return v,'min'
    if 'in hours' in dl or 'hour' in dl: return v,'h'
    return v,''  # desconocida -> normalizar la deja pendiente

def especial(valnum,unit):
    if valnum in ("","NO_ENCONTRADO","null"): return True
    if not re.match(r'^-?\d+(\.\d+)?$',valnum): return True   # relativo/no numerico
    return float(valnum)==0 or float(valnum)<0

PROJECTS=[("hdfs","stable (2026-07-29)","https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/hdfs-default.xml",hadoop,f"{RAW}/hdfs/config.html"),
          ("yarn","stable (2026-07-29)","https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-common/yarn-default.xml",hadoop,f"{RAW}/yarn/config.html"),
          ("hbase","2.x (Reference Guide, 2026-07-29)","https://hbase.apache.org/book.html#config.files",hbase,f"{RAW}/hbase/config.html"),
          ("cassandra","5.0","https://cassandra.apache.org/doc/5.0/cassandra/managing/configuration/cass_yaml_file.html",cassandra,f"{RAW}/cassandra/config.html")]

cols=["id","proyecto","version_doc","parametro","valor_original","unidad_original","valor_ms","es_valor_especial","tipo_timeout","clasificado_por","descripcion_oficial","fuente_url","fecha_consulta","notas"]
existing=list(csv.DictReader(open("datos/dataset_timeouts.csv",encoding="utf-8")))
# idempotente: descarta filas previas de estos 4 proyectos antes de re-anexar
_PROJ4={"hdfs","yarn","hbase","cassandra"}
existing=[r for r in existing if r["proyecto"] not in _PROJ4]
_id=max((int(r["id"]) for r in existing),default=0)
newrows=[]; excl={}
for proj,ver,url,fn,path in PROJECTS:
    for name,val,desc in fn(path):
        if not TIMEOUT.search(name): continue
        ex=is_excluded(name,val,desc)
        if ex: excl[ex]=excl.get(ex,0)+1; continue
        vnum,unit=split_unit(val,name,desc)
        esp=especial(vnum,unit)
        border="REVISAR_ALCANCE: periodico/retencion/cache (protocolo 2.bis)" if BORDER.search(name) or BORDER.search(desc) else ""
        tipo="OTRO" if border else tipo_of(name,desc)
        notas=border
        if tipo=="OTRO" and not border:
            notas="revisar categoria (propuesta automatica no concluyente)"
        if val!=vnum or (unit and val.lower()!=(vnum+unit).lower()):
            pass
        anchor = url + ("" if "#" in url else "")
        if proj in ("hdfs","yarn"): furl=url  # xml no tiene anchor por prop
        elif proj=="hbase": furl=f"https://hbase.apache.org/book.html#{name}"
        else: furl=f"https://cassandra.apache.org/doc/5.0/cassandra/managing/configuration/cass_yaml_file.html#{name}"
        _id+=1
        newrows.append({"id":_id,"proyecto":proj,"version_doc":ver,"parametro":name,
            "valor_original":vnum if vnum else "NO_ENCONTRADO","unidad_original":unit,"valor_ms":"",
            "es_valor_especial":"true" if esp else "false","tipo_timeout":tipo,
            "descripcion_oficial":desc[:110],"fuente_url":furl,"fecha_consulta":FECHA,"notas":notas})

with open("datos/dataset_timeouts.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(existing+newrows)

from collections import Counter
print("Filas nuevas:",len(newrows),"| por proyecto:",dict(Counter(r["proyecto"] for r in newrows)))
print("por tipo:",dict(Counter(r["tipo_timeout"] for r in newrows)))
print("REVISAR_ALCANCE:",sum(1 for r in newrows if r["notas"]))
print("especiales nuevos:",sum(1 for r in newrows if r["es_valor_especial"]=="true"))
print("EXCLUIDOS (no-timeouts):",dict(excl),"=",sum(excl.values()))
print("TOTAL dataset:",len(existing)+len(newrows))
