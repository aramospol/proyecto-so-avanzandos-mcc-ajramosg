#!/usr/bin/env python3
"""Normaliza valor_original + unidad_original a valor_ms en el dataset maestro.

Determinista y conservador: solo convierte unidades de la tabla FACTOR_MS.
- es_valor_especial = true  -> valor_ms queda vacío (nunca se normaliza).
- unidad desconocida        -> valor_ms queda vacío y se reporta en stderr
                               (p. ej. "ticks" requiere decisión humana).
- valor no numérico         -> igual que unidad desconocida.

Uso:
    python scripts/normalizar.py datos/dataset_timeouts.csv

Escribe el resultado en el mismo archivo (respaldo previo en *.bak) y reporta
cuántas filas se normalizaron y cuáles quedaron pendientes.
"""

import csv
import shutil
import sys

FACTOR_MS = {
    "ms": 1,
    "milisegundos": 1,
    "milliseconds": 1,
    "s": 1000,
    "seg": 1000,
    "segundos": 1000,
    "seconds": 1000,
    "sec": 1000,
    "min": 60_000,
    "minutos": 60_000,
    "minutes": 60_000,
    "h": 3_600_000,
    "horas": 3_600_000,
    "hours": 3_600_000,
}


def normalizar_fila(fila: dict) -> str:
    """Devuelve 'ok', 'especial' o un motivo de pendiente."""
    if fila["es_valor_especial"].strip().lower() == "true":
        fila["valor_ms"] = ""
        return "especial"

    unidad = fila["unidad_original"].strip().lower()
    if unidad not in FACTOR_MS:
        fila["valor_ms"] = ""
        return f"unidad desconocida: '{fila['unidad_original']}'"

    try:
        valor = float(fila["valor_original"].strip().replace(",", ""))
    except ValueError:
        fila["valor_ms"] = ""
        return f"valor no numérico: '{fila['valor_original']}'"

    ms = valor * FACTOR_MS[unidad]
    fila["valor_ms"] = str(int(ms)) if ms == int(ms) else str(ms)
    return "ok"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    ruta = sys.argv[1]
    shutil.copy2(ruta, ruta + ".bak")

    with open(ruta, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas = lector.fieldnames
        filas = list(lector)

    ok, especiales, pendientes = 0, 0, []
    for fila in filas:
        resultado = normalizar_fila(fila)
        if resultado == "ok":
            ok += 1
        elif resultado == "especial":
            especiales += 1
        else:
            pendientes.append((fila["id"], fila["proyecto"], fila["parametro"], resultado))

    with open(ruta, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)

    print(f"Normalizadas: {ok} | Especiales (sin valor_ms): {especiales} | Pendientes: {len(pendientes)}")
    for id_, proyecto, parametro, motivo in pendientes:
        print(f"  PENDIENTE id={id_} {proyecto}/{parametro}: {motivo}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
