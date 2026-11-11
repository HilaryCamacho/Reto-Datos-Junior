"""Verifica que el proyecto se puede correr dos veces sin duplicar nada.

Trabaja en una COPIA temporal (empieza sin deacero.duckdb, como lo haría quien evalúa),
corre `dbt build` dos veces y compara, tabla por tabla, el número de filas y un hash del
contenido. Si algo se duplicara o cambiara entre corridas, el hash difiere y el script falla.

Uso (desde la raíz del repo, con el entorno virtual activo):
    python tools/verificar_idempotencia.py
"""
import argparse
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import copiar_proyecto, correr_dbt, fallidos  # noqa: E402

ESQUEMAS = ("landing_fle", "landing_vta", "landing_opc", "silver_logistica", "gold_logistica", "mart_logistica")


def huella(db: Path) -> dict:
    """{esquema.tabla: (filas, hash md5 del contenido ordenado)} para las tablas del proyecto."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        tablas = con.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_type = 'BASE TABLE' and table_schema in (%s) order by 1, 2"
            % ",".join("'%s'" % e for e in ESQUEMAS)
        ).fetchall()
        out = {}
        for esquema, tabla in tablas:
            nombre = "%s.%s" % (esquema, tabla)
            filas, md5 = con.execute(
                "select count(*), md5(string_agg(cast(t as varchar), '|' order by cast(t as varchar))) "
                "from %s as t" % nombre
            ).fetchone()
            out[nombre] = (filas, md5)
        return out
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="carpeta donde crear la copia temporal")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(dir=args.dir) as tmp:
        proyecto = copiar_proyecto(Path(tmp) / "proyecto")
        huellas = []
        for n in (1, 2):
            correr_dbt(proyecto, "build")
            malos = fallidos(proyecto)
            if malos:
                print("La corrida %d tuvo fallas: %s" % (n, malos))
                return 2
            huellas.append(huella(proyecto / "deacero.duckdb"))

    primera, segunda = huellas
    print("| Tabla | Filas 1ª corrida | Filas 2ª corrida | Contenido idéntico |")
    print("|---|---|---|---|")
    difiere = 0
    for nombre in sorted(primera):
        f1, h1 = primera[nombre]
        f2, h2 = segunda.get(nombre, (None, None))
        igual = (f1, h1) == (f2, h2)
        difiere += 0 if igual else 1
        print("| `%s` | %s | %s | %s |" % (nombre, f1, f2, "sí" if igual else "NO"))
    if set(primera) != set(segunda):
        difiere += 1
        print("\nLas tablas existentes difieren entre corridas.")
    print("\n%s" % ("IDEMPOTENTE: las %d tablas quedaron idénticas." % len(primera) if not difiere
                    else "NO idempotente: %d tablas difieren." % difiere))
    return 1 if difiere else 0


if __name__ == "__main__":
    sys.exit(main())
