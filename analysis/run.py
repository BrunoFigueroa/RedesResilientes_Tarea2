"""Pipeline de analisis:
  1) ATTR antes del terremoto: enlaces.p_falla = 0 (valor por defecto en la BD)
  2) Probabilidad de falla de cada enlace (modelo desde el epicentro) -> se
     escribe /output/prob_falla.sql y se aplica a la BD (prob_falla + enlaces.p_falla)
  3) ATTR despues del terremoto: Monte Carlo con enlaces.p_falla leido de la BD
  4) Tests: sensibilidad al modelo de vulnerabilidad y convergencia del Monte Carlo
Resultados -> /output/resultados.json y tablas resultados_attr / conectividad_nodos_clave
(main.sql, el dump completo de la BD, lo genera main.py con pg_dump).
"""
import json
import os
import time

import attr
import fallas
import sensibilidad
from grafo import cargar_pf, componentes, conectar, s_lcc
from montecarlo import Red, simular

MC_ITER = int(os.environ.get("MC_ITER", "2000"))
MC_SEED = int(os.environ.get("MC_SEED", "42"))
OUT = "/output"


def mostrar_extremos(cur, n=5):
    for titulo, orden in (("mas", "DESC"), ("menos", "ASC")):
        cur.execute(f"""SELECT enlace_id, tipo, round(largo_km::numeric, 1), round(dist_epi_min_km::numeric, 0),
                               round(pga_max_g::numeric, 3), p_falla
                        FROM prob_falla WHERE largo_km >= 5 ORDER BY p_falla {orden}, dist_epi_min_km {'ASC' if orden == 'DESC' else 'DESC'}
                        LIMIT %s""", (n,))
        print(f"[analysis]    Enlaces {titulo} afectados, largo >= 5 km (id, tipo, km, R_epi km, PGA g, P_f):")
        for r in cur.fetchall():
            print(f"[analysis]      {r[0]:5d} {r[1]:7s} {r[2]:7} {r[3]:6} {r[4]:6} {r[5]:.6f}")


def main():
    t0 = time.time()
    with conectar() as conn, conn.cursor() as cur:
        print("[analysis] 1) ATTR antes del terremoto (enlaces.p_falla = 0)...")
        cur.execute("UPDATE enlaces SET p_falla = 0")   # estado en operacion
        conn.commit()
        antes = attr.calcular(cur)                       # exacto + pgr_connectedComponents
        red = Red(cur)
        pf0 = cargar_pf(cur)
        assert all(p == 0 for p in pf0.values())
        mc0 = simular(red, pf0, MC_ITER, MC_SEED, detalle=False)   # mismo estimador que "despues"
        assert abs(mc0["attr_nodos_clave"] - antes["attr_nodos_clave"]) < 1e-12
        uf = componentes(red.nodos, [(u, v) for u, v, _ in red.logicos])
        antes["s_lcc_nodos_red"] = s_lcc(uf, red.nodos_red)
        print(f"[analysis]    ATTR nodos clave = {antes['attr_nodos_clave']:.4f}  "
              f"(componentes con nodos clave: {antes['componentes_nodos_clave']}; "
              f"nodos de red: {antes['attr_nodos_red']:.4f})")

        print(f"[analysis] 2) Probabilidades de falla ({fallas.MODELOS[fallas.MODELO_PRINCIPAL]['desc']})...")
        sismo, sub = fallas.cargar_subtramos(cur)
        res = fallas.probabilidades(sub, fallas.MODELO_PRINCIPAL)
        path_sql = os.path.join(OUT, "prob_falla.sql")
        fallas.escribir_sql_probabilidades(path_sql, sismo, res)
        cur.execute(open(path_sql).read())
        conn.commit()
        cur.execute("SELECT count(*), avg(p_falla), max(p_falla), min(p_falla), sum(n_reparaciones_esp) "
                    "FROM prob_falla")
        n, pm, px, pn, nrep = cur.fetchone()
        print(f"[analysis]    {n} enlaces actualizados en la BD (P_f media={pm:.4f}, max={px:.4f}, "
              f"min={pn:.2e}, reparaciones esperadas={nrep:.1f})")
        mostrar_extremos(cur)

        print(f"[analysis] 3) ATTR despues del terremoto (Monte Carlo, {MC_ITER} iter, enlaces.p_falla)...")
        pf = cargar_pf(cur)
        despues = simular(red, pf, MC_ITER, MC_SEED)
        despues.pop("serie")
        dif = despues["attr_nodos_clave"] - antes["attr_nodos_clave"]
        despues["diferencia_attr"] = dif
        despues["variacion_pct"] = 100 * dif / antes["attr_nodos_clave"]
        print(f"[analysis]    ATTR nodos clave = {despues['attr_nodos_clave']:.4f} "
              f"+/- {despues['attr_nodos_clave_std']:.4f}  (diferencia {dif:+.4f}, "
              f"{despues['variacion_pct']:+.1f} %; nodos de red: {despues['attr_nodos_red']:.4f})")

        print("[analysis] 4) Tests: sensibilidad al modelo y convergencia Monte Carlo...")
        tests = {
            "modelos": sensibilidad.test_modelos(red, sub, MC_ITER, MC_SEED),
            "convergencia": sensibilidad.test_convergencia(red, pf, MC_SEED),
        }
        for t in tests["modelos"]:
            print(f"[analysis]    {t['modelo']:13s} ATTR clave={t['attr_nodos_clave']:.4f}  "
                  f"red={t['attr_nodos_red']:.4f}  S_LCC={t['s_lcc_nodos_red']:.4f}")
        for c in tests["convergencia"]["por_iteraciones"]:
            print(f"[analysis]    N={c['iteraciones']:5d}  ATTR={c['attr_medio']:.4f} "
                  f"+/- {c['ic95_semiancho']:.4f}")
        es = tests["convergencia"]["entre_semillas"]
        print(f"[analysis]    {es['semillas']} semillas x {es['iteraciones']}: "
              f"media={es['media']:.4f} sd={es['desv_std']:.4f}")

        resultados = {
            "sismo": sismo,
            "modelo_falla": {
                "atenuacion": "Youngs et al. (1997), interfase, roca, desde el epicentro",
                "pgv": "Newmark & Hall (1982): PGV = 121.9 cm/s por g (suelo competente)",
                "vulnerabilidad": fallas.MODELOS[fallas.MODELO_PRINCIPAL]["desc"]
                                  + ": RR = 0.3*0.0001*PGV^2.25 [rep/km]",
                "probabilidad": "P_f = 1 - exp(-sum RR*L)",
            },
            "antes": antes, "despues": despues, "tests": tests,
        }

        cur.execute("""
            DROP TABLE IF EXISTS resultados_attr;
            CREATE TABLE resultados_attr (escenario text PRIMARY KEY,
                attr_nodos_clave double precision, attr_nodos_red double precision,
                s_lcc_nodos_red double precision);
            INSERT INTO resultados_attr VALUES ('antes', %s, %s, %s), ('despues', %s, %s, %s);
            DROP TABLE IF EXISTS conectividad_nodos_clave;
            CREATE TABLE conectividad_nodos_clave (nodo_id integer PRIMARY KEY,
                p_conectado_ixp double precision);
        """, (antes["attr_nodos_clave"], antes["attr_nodos_red"], antes["s_lcc_nodos_red"],
              despues["attr_nodos_clave"], despues["attr_nodos_red"], despues["s_lcc_nodos_red"]))
        for n in despues["p_conexion_ixp"]:
            cur.execute("INSERT INTO conectividad_nodos_clave VALUES (%s, %s)",
                        (n["id"], n["p_conectado_ixp"]))
        conn.commit()

    with open(os.path.join(OUT, "resultados.json"), "w") as fh:
        json.dump(resultados, fh, indent=2, ensure_ascii=False)
    print(f"[analysis] OK ({time.time() - t0:.1f} s)")


if __name__ == "__main__":
    main()
