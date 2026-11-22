"""Verifica main.sql: se ejecuta contra una BD VACIA en la que main.py cargo
main.sql (PGDATABASE=resiliencia_check). Recalcula el ATTR antes (p_falla = 0)
y despues (p_falla leido de la BD) y lo compara con /output/resultados.json.
"""
import json
import os
import sys

from grafo import conectar
from montecarlo import Red, simular

MC_ITER = int(os.environ.get("MC_ITER", "2000"))
MC_SEED = int(os.environ.get("MC_SEED", "42"))


def main():
    ref = json.load(open("/output/resultados.json"))
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        db = cur.fetchone()[0]
        print(f"[verificar] BD cargada desde main.sql: {db}")
        for t in ("enlaces", "enlaces_vertices_pgr", "nodos_clave", "sismo", "prob_falla"):
            cur.execute(f"SELECT count(*) FROM {t}")
            print(f"[verificar]   {t:22s} {cur.fetchone()[0]:6d} filas")
        cur.execute("SELECT count(*), count(*) FILTER (WHERE p_falla > 0), min(p_falla), max(p_falla) "
                    "FROM enlaces")
        n, npos, pmin, pmax = cur.fetchone()
        print(f"[verificar]   enlaces.p_falla: {npos}/{n} > 0, rango [{pmin:.2e}, {pmax:.4f}]")

        red = Red(cur)
        cur.execute("SELECT id, p_falla FROM enlaces ORDER BY id")
        pf = {i: float(p) for i, p in cur.fetchall()}
        antes = simular(red, {e: 0.0 for e in pf}, MC_ITER, MC_SEED, detalle=False)["attr_nodos_clave"]
        despues = simular(red, pf, MC_ITER, MC_SEED, detalle=False)["attr_nodos_clave"]

    ok = (abs(antes - ref["antes"]["attr_nodos_clave"]) < 1e-9
          and abs(despues - ref["despues"]["attr_nodos_clave"]) < 1e-9)
    print(f"[verificar]   ATTR antes   = {antes:.4f}  (pipeline: {ref['antes']['attr_nodos_clave']:.4f})")
    print(f"[verificar]   ATTR despues = {despues:.4f}  (pipeline: {ref['despues']['attr_nodos_clave']:.4f})")
    print(f"[verificar] {'OK: main.sql reproduce los resultados' if ok else 'ERROR: no coincide'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
