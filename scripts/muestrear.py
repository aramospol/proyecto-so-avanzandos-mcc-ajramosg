#!/usr/bin/env python3
"""Muestreo aleatorio estratificado del dataset maestro (semana 4).

Dos modos:

  validacion      -> `validacion/muestra_anotador2.csv` (ciega, sin la etiqueta del
                     anotador 1) + `validacion/clave_muestra_anotador2.csv` (llave
                     id_muestra -> id dataset + etiqueta del anotador 1; NO se
                     entrega al anotador 2, la usa `scripts/kappa.py`).
  justificaciones -> `datos/justificaciones.csv` con la muestra a investigar en
                     JIRA/commits/listas; las columnas de contenido quedan en
                     PENDIENTE para que las llene el estudiante.

Diseño del muestreo (determinista y reproducible):
- Estratos = valores de `tipo_timeout` (decisión pendiente de confirmación humana,
  ver protocolo §7 y §8).
- Asignación proporcional al tamaño del estrato, con piso de MIN_POR_ESTRATO filas
  por estrato (o todo el estrato si es más pequeño); el residuo se reparte por
  mayor resto hasta alcanzar n exacto.
- Selección dentro del estrato con `random.Random(semilla).sample` y orden final
  mezclado con el mismo generador -> misma semilla, misma muestra.

Uso:
    python scripts/muestrear.py validacion --n 60 --semilla 20260808
    python scripts/muestrear.py justificaciones --n 40 --semilla 20260808
    (añadir --force para sobrescribir un archivo que ya tiene filas)
"""

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

# La consola de Windows suele ser cp1252: evita que el reporte falle por "→", "…".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


RAIZ = Path(__file__).resolve().parent.parent
DATASET = RAIZ / "datos" / "dataset_timeouts.csv"
MUESTRA_VAL = RAIZ / "validacion" / "muestra_anotador2.csv"
CLAVE_VAL = RAIZ / "validacion" / "clave_muestra_anotador2.csv"
JUSTIF = RAIZ / "datos" / "justificaciones.csv"

MIN_POR_ESTRATO = 2
# Una semilla distinta por modo para que la muestra de justificaciones no quede
# correlacionada con la de validación (misma semilla -> misma secuencia aleatoria).
SEMILLAS = {"validacion": 20260808, "justificaciones": 20260809}

COLS_MUESTRA = [
    "id_muestra",
    "proyecto",
    "parametro",
    "valor_original",
    "unidad_original",
    "descripcion_oficial",
    "fuente_url",
    "tipo_timeout_anotador2",
    "notas_anotador2",
]

COLS_CLAVE = ["id_muestra", "id", "proyecto", "parametro", "tipo_timeout_anotador1"]

COLS_JUSTIF = [
    "id",
    "proyecto",
    "parametro",
    "valor_original",
    "unidad_original",
    "tipo_timeout",
    "justificacion_texto_resumen",
    "tipo_justificacion",
    "justificacion_url",
    "donde_busque",
    "fecha_consulta",
    "notas",
]


def leer_dataset() -> list:
    with open(DATASET, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def asignar(estratos: dict, n: int, piso: int) -> dict:
    """Reparte n filas entre estratos.

    1. Cuota proporcional al tamaño del estrato, repartiendo los sobrantes por
       resto mayor (método de Hare).
    2. Los estratos que queden por debajo del piso se suben al piso (o a su
       tamaño, si es menor), quitando filas a los estratos con mayor exceso
       sobre su cuota exacta y que sigan por encima de su propio piso.
    """
    total = sum(len(v) for v in estratos.values())
    if n > total:
        raise SystemExit(f"n={n} excede el tamaño del dataset ({total} filas)")

    exacto = {c: n * len(f) / total for c, f in estratos.items()}
    cuotas = {c: min(int(v), len(estratos[c])) for c, v in exacto.items()}

    sobrantes = n - sum(cuotas.values())
    for clave in sorted(exacto, key=lambda c: (exacto[c] - int(exacto[c]), len(estratos[c])), reverse=True):
        if sobrantes <= 0:
            break
        if cuotas[clave] < len(estratos[clave]):
            cuotas[clave] += 1
            sobrantes -= 1

    for clave in sorted(cuotas):
        objetivo = min(piso, len(estratos[clave]))
        while cuotas[clave] < objetivo:
            donantes = [
                c for c in cuotas
                if c != clave and cuotas[c] > min(piso, len(estratos[c]))
            ]
            if not donantes:
                break
            donante = max(donantes, key=lambda c: cuotas[c] - exacto[c])
            cuotas[donante] -= 1
            cuotas[clave] += 1
    return cuotas


def muestrear(filas: list, n: int, semilla: int, piso: int):
    estratos = defaultdict(list)
    for fila in filas:
        estratos[fila["tipo_timeout"]].append(fila)
    for clave in estratos:
        estratos[clave].sort(key=lambda f: int(f["id"]))  # orden estable antes de sortear

    rng = random.Random(semilla)
    cuotas = asignar(estratos, n, piso)

    seleccion = []
    print(f"Estratos (tipo_timeout) | dataset -> muestra")
    for clave in sorted(estratos):
        elegidas = rng.sample(estratos[clave], cuotas[clave])
        seleccion.extend(elegidas)
        print(f"  {clave:<22} {len(estratos[clave]):>4} -> {cuotas[clave]}")
    rng.shuffle(seleccion)
    print(f"Total muestra: {len(seleccion)} de {len(filas)} filas ({len(seleccion)/len(filas):.0%})")
    return seleccion


def tiene_filas(ruta: Path) -> bool:
    if not ruta.exists():
        return False
    with open(ruta, newline="", encoding="utf-8") as f:
        return any(True for _ in csv.DictReader(f))


def escribir(ruta: Path, columnas: list, filas: list) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"Escrito {ruta.relative_to(RAIZ)} ({len(filas)} filas)")


def modo_validacion(seleccion: list, semilla: int, force: bool) -> None:
    for ruta in (MUESTRA_VAL, CLAVE_VAL):
        if tiene_filas(ruta) and not force:
            raise SystemExit(
                f"{ruta.relative_to(RAIZ)} ya tiene filas; usa --force si de verdad "
                "quieres reemplazar la muestra (perderías la anotación existente)"
            )

    muestra, clave = [], []
    for i, fila in enumerate(seleccion, start=1):
        idm = f"M{i:03d}"
        muestra.append(
            {
                "id_muestra": idm,
                "proyecto": fila["proyecto"],
                "parametro": fila["parametro"],
                "valor_original": fila["valor_original"],
                "unidad_original": fila["unidad_original"],
                "descripcion_oficial": fila.get("descripcion_oficial", ""),
                "fuente_url": fila["fuente_url"],
                "tipo_timeout_anotador2": "",
                "notas_anotador2": "",
            }
        )
        clave.append(
            {
                "id_muestra": idm,
                "id": fila["id"],
                "proyecto": fila["proyecto"],
                "parametro": fila["parametro"],
                "tipo_timeout_anotador1": fila["tipo_timeout"],
            }
        )
    escribir(MUESTRA_VAL, COLS_MUESTRA, muestra)
    escribir(CLAVE_VAL, COLS_CLAVE, clave)
    print(f"Semilla usada: {semilla} (anótala en validacion/kappa_resultados.md)")
    print("RECORDATORIO: clave_muestra_anotador2.csv NO se entrega al anotador 2.")


def modo_justificaciones(seleccion: list, semilla: int, force: bool) -> None:
    if tiene_filas(JUSTIF) and not force:
        raise SystemExit(
            f"{JUSTIF.relative_to(RAIZ)} ya tiene filas; usa --force solo si quieres "
            "reemplazar la muestra (perderías el trabajo de búsqueda ya hecho)"
        )
    filas = []
    for fila in sorted(seleccion, key=lambda f: (f["proyecto"], f["parametro"])):
        filas.append(
            {
                "id": fila["id"],
                "proyecto": fila["proyecto"],
                "parametro": fila["parametro"],
                "valor_original": fila["valor_original"],
                "unidad_original": fila["unidad_original"],
                "tipo_timeout": fila["tipo_timeout"],
                "justificacion_texto_resumen": "PENDIENTE",
                "tipo_justificacion": "PENDIENTE",
                "justificacion_url": "PENDIENTE",
                "donde_busque": "PENDIENTE",
                "fecha_consulta": "PENDIENTE",
                "notas": "",
            }
        )
    escribir(JUSTIF, COLS_JUSTIF, filas)
    print(f"Semilla usada: {semilla} (anótala en el protocolo §7)")
    print("Las celdas PENDIENTE las llena el estudiante tras buscar en JIRA/commits/listas.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modo", choices=["validacion", "justificaciones"])
    ap.add_argument("--n", type=int, default=None, help="tamaño de la muestra (60 / 40 por defecto)")
    ap.add_argument("--semilla", type=int, default=None, help="por defecto: 20260808 / 20260809")
    ap.add_argument("--piso", type=int, default=MIN_POR_ESTRATO, help="mínimo de filas por estrato")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    n = args.n if args.n is not None else (60 if args.modo == "validacion" else 40)
    semilla = args.semilla if args.semilla is not None else SEMILLAS[args.modo]
    filas = leer_dataset()
    seleccion = muestrear(filas, n, semilla, args.piso)

    if args.modo == "validacion":
        modo_validacion(seleccion, semilla, args.force)
    else:
        modo_justificaciones(seleccion, semilla, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
