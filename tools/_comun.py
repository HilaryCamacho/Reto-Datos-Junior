"""Utilidades compartidas por las herramientas de tools/ (solo biblioteca estándar)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DBT = Path(sys.executable).parent / "dbt"

# Lo que NO se copia: entorno virtual, artefactos generados, base de datos y git.
_IGNORAR = shutil.ignore_patterns(
    ".venv", "target", "logs", ".git", "__pycache__", "*.duckdb", "*.duckdb.wal", "dbt_packages"
)


def copiar_proyecto(destino: Path) -> Path:
    """Copia el proyecto a `destino` para trabajar sin tocar el repositorio ni su deacero.duckdb."""
    shutil.copytree(RAIZ, destino, ignore=_IGNORAR)
    return destino


def correr_dbt(proyecto: Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta dbt dentro de `proyecto` (perfil local, sin credenciales ni telemetría)."""
    env = dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS="false")
    return subprocess.run(
        [str(DBT), *args], cwd=str(proyecto), env=env, capture_output=True, text=True
    )


def resultados(proyecto: Path) -> list:
    """Lee target/run_results.json de la última corrida de dbt."""
    ruta = proyecto / "target" / "run_results.json"
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text())["results"]


def fallidos(proyecto: Path) -> list:
    """Nombres cortos de las pruebas/modelos que fallaron o dieron error en la última corrida."""
    nombres = []
    for r in resultados(proyecto):
        if r["status"] in ("fail", "error"):
            partes = r["unique_id"].split(".")
            if partes[0] == "unit_test":
                nombres.append("unit:" + partes[-1])  # unit_test.<proyecto>.<modelo>.<nombre>
            else:
                nombres.append(partes[2] if len(partes) > 2 else r["unique_id"])
    return sorted(nombres)
