#!/usr/bin/env python3
"""Tarea 2 - Resiliencia de la infraestructura de Internet chilena ante el sismo 8.8.

Orquesta los contenedores Docker (sin dependencias Python externas):
    python3 main.py            pipeline completo: BD -> carga -> topologia -> ATTR antes ->
                               probabilidades de falla -> ATTR despues -> main.sql ->
                               carga main.sql en una BD vacia y verifica -> mapa
    python3 main.py attr       muestra ATTR antes/despues (recalcula el analisis)
    python3 main.py verificar  carga main.sql en una BD vacia y recalcula el ATTR
    python3 main.py mapa       abre el mapa en el navegador
    python3 main.py down       detiene los contenedores (--purge borra tambien la BD)

Variables opcionales: DB_PORT (5432), WEB_PORT (8080), MC_ITER (2000), MC_SEED (42)
"""
import json
import os
import socket
import subprocess
import sys
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "output")
ENV = {**os.environ,
       "HOST_UID": str(os.getuid()) if hasattr(os, "getuid") else "1000",
       "HOST_GID": str(os.getgid()) if hasattr(os, "getgid") else "1000"}


def compose(*args, check=True):
    cmd = ["docker", "compose", *args]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=ENV, check=check)


def puerto_ocupado(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def db_corriendo():
    r = subprocess.run(["docker", "compose", "ps", "--status", "running", "-q", "db"],
                       cwd=ROOT, env=ENV, capture_output=True, text=True)
    return bool(r.stdout.strip())


TABLAS_MAIN_SQL = ["enlaces", "enlaces_vertices_pgr", "nodos_clave", "sismo", "prob_falla",
                   "resultados_attr", "conectividad_nodos_clave", "intersecciones"]
CABECERA_MAIN_SQL = """-- =====================================================================
-- main.sql : infraestructura + probabilidad de falla de cada enlace
-- Tarea 2 - Resiliencia de la Internet chilena ante el sismo M8.8 (Maule 2010)
--
-- Generado por main.py (pg_dump). Carga en una BD vacia con PostGIS y pgRouting:
--     createdb nueva && psql -d nueva -v ON_ERROR_STOP=1 -f main.sql
-- Tablas:
--   enlaces               segmentos de la red (source/target de pgr_createTopology),
--                         origen/sintetico y p_falla (probabilidad de falla, 0 en operacion)
--   enlaces_vertices_pgr  vertices de pgr_createTopology (+ grado, tipo, es_clave)
--   nodos_clave           19 nodos que generan / intercambian / reciben informacion
--   sismo                 evento USGS official20100227063411530_30 (GeoJSON)
--   prob_falla            detalle del modelo por enlace (distancia, PGA, PGV, RR*L, P_f)
--   resultados_attr       ATTR antes / despues;  conectividad_nodos_clave: P(conectado al IXP)
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

"""


def generar_main_sql():
    """main.sql = dump completo (infraestructura + probabilidades) de la BD."""
    args = ["exec", "-T", "db", "pg_dump", "-U", "postgres", "-d", "resiliencia",
            "--no-owner", "--no-privileges"]
    for t in TABLAS_MAIN_SQL:
        args += ["-t", f"public.{t}"]
    cmd = ["docker", "compose", *args]
    print("$", " ".join(cmd), "> main.sql", flush=True)
    r = subprocess.run(cmd, cwd=ROOT, env=ENV, check=True, capture_output=True, text=True)
    path = os.path.join(ROOT, "main.sql")
    with open(path, "w") as fh:
        fh.write(CABECERA_MAIN_SQL + r.stdout)
    print(f"main.sql -> {path} ({os.path.getsize(path) / 1e6:.1f} MB)")


def verificar_main_sql():
    """Carga main.sql en una BD vacia (resiliencia_check) y recalcula el ATTR."""
    path = os.path.join(ROOT, "main.sql")
    if not os.path.exists(path):
        sys.exit("No existe main.sql. Ejecuta primero: python3 main.py")
    psql = ["exec", "-T", "db", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q"]
    compose(*psql, "-c", "DROP DATABASE IF EXISTS resiliencia_check")
    compose(*psql, "-c", "CREATE DATABASE resiliencia_check")
    print("$ docker compose exec -T db psql -d resiliencia_check -f - < main.sql", flush=True)
    with open(path) as fh:
        subprocess.run(["docker", "compose", *psql, "-d", "resiliencia_check"],
                       cwd=ROOT, env=ENV, check=True, stdin=fh)
    compose("run", "--rm", "--no-deps", "-e", "PGDATABASE=resiliencia_check",
            "analysis", "python", "-u", "verificar.py")
    compose(*psql, "-c", "DROP DATABASE resiliencia_check")


def mostrar_attr():
    path = os.path.join(OUTPUT, "resultados.json")
    if not os.path.exists(path):
        sys.exit("No hay resultados. Ejecuta primero: python3 main.py")
    r = json.load(open(path))
    a, d, s = r["antes"], r["despues"], r["sismo"]
    print("\n" + "=" * 64)
    print(f" Sismo: {s['lugar']}  M{s['magnitud']}  ({s['usgs_id']})")
    print(f" Red: {a['n_enlaces_segmentos']} segmentos -> {a['n_enlaces_logicos']} enlaces logicos,"
          f" {a['n_intersecciones']} intersecciones, {a['n_nodos_clave']} nodos clave")
    print("-" * 64)
    print(f" {'ATTR':22s} {'Antes':>10s} {'Despues':>12s}")
    print(f" {'Nodos clave':22s} {a['attr_nodos_clave']:10.4f} {d['attr_nodos_clave']:12.4f}"
          f"  (+/- {d['attr_nodos_clave_std']:.4f})")
    print(f" {'  diferencia':22s} {'':10s} {d['diferencia_attr']:+12.4f}  ({d['variacion_pct']:+.1f} %)")
    print(f" {'Nodos de red (FR)':22s} {a['attr_nodos_red']:10.4f} {d['attr_nodos_red']:12.4f}")
    print(f" {'S_LCC (ENRN)':22s} {a['s_lcc_nodos_red']:10.4f} {d['s_lcc_nodos_red']:12.4f}")
    print(f" Monte Carlo: {d['iteraciones']} iteraciones, semilla {d['semilla']}")
    print(f" Modelo: {r['modelo_falla']['vulnerabilidad']}")
    t = r.get("tests")
    if t:
        print("-" * 64)
        print(" Test de sensibilidad (ATTR nodos clave despues):")
        for m in t["modelos"]:
            print(f"   {m['attr_nodos_clave']:6.4f}  {m['descripcion']}")
        es = t["convergencia"]["entre_semillas"]
        print(f" Convergencia: {es['semillas']} semillas x {es['iteraciones']} iter ->"
              f" sd entre semillas = {es['desv_std']:.4f}")
    print("-" * 64)
    print(" P(nodo clave sigue conectado al IXP de Santiago):")
    for n in d["p_conexion_ixp"]:
        print(f"   {n['p_conectado_ixp']:6.3f}  {n['nombre']}")
    print("=" * 64 + "\n")


def pipeline():
    db_port = int(ENV.get("DB_PORT", "5432"))
    if not db_corriendo() and puerto_ocupado(db_port):
        sys.exit(f"El puerto {db_port} esta ocupado (¿PostgreSQL local activo?).\n"
                 f"  Desactivalo:  sudo systemctl disable --now postgresql\n"
                 f"  o usa otro:   DB_PORT=5433 python3 main.py")
    os.makedirs(OUTPUT, exist_ok=True)
    compose("build")
    compose("up", "-d", "--wait", "db")
    compose("run", "--rm", "--no-deps", "sismo")
    compose("run", "--rm", "--no-deps", "loader")
    compose("run", "--rm", "--no-deps", "analysis")
    generar_main_sql()
    verificar_main_sql()
    compose("up", "-d", "--no-deps", "--force-recreate", "web")
    mostrar_attr()
    abrir_mapa()


def abrir_mapa():
    url = f"http://localhost:{ENV.get('WEB_PORT', '8080')}/mapa.html"
    print(f"Mapa: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    accion = sys.argv[1] if len(sys.argv) > 1 else "todo"
    if accion == "todo":
        pipeline()
    elif accion == "attr":
        if not db_corriendo():
            sys.exit("La BD no esta corriendo. Ejecuta primero: python3 main.py")
        compose("run", "--rm", "--no-deps", "analysis")
        mostrar_attr()
    elif accion == "verificar":
        if not db_corriendo():
            sys.exit("La BD no esta corriendo. Ejecuta primero: python3 main.py")
        verificar_main_sql()
    elif accion == "mapa":
        abrir_mapa()
    elif accion == "down":
        compose("down", *(["-v"] if "--purge" in sys.argv else []))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
