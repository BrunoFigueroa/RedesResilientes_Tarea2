"""Modelo probabilistico de falla de enlaces a partir del epicentro del sismo.

1) Movimiento del suelo: PGA mediana con la ley de atenuacion de
   Youngs, Chiou, Silva & Humphrey (1997), sismos de subduccion interplaca, roca (Zt = 0):
       ln PGA[g] = 0.2418 + 1.414 M - 2.552 ln(R + 1.7818 e^(0.554 M)) + 0.00607 H
   R = distancia hipocentral [km] = sqrt(R_epi^2 + H^2),  H = profundidad [km]

2) PGV a partir de PGA (Newmark & Hall, 1982, suelo competente): PGV/PGA = 48 in/s/g
   (los cables siguen caminos sobre suelo; la PGA de Youngs es para roca, ver informe)
       PGV [cm/s] = 121.9 * PGA[g]

3) Tasa de reparaciones por propagacion de ondas, relacion empirica de
   O'Rourke & Ayala (1993) adoptada por HAZUS (FEMA) para lineas enterradas:
       RR [rep/km] = K * 0.0001 * PGV[cm/s]^2.25
   K = 1.0 materiales fragiles, K = 0.3 materiales ductiles. El cable de fibra
   (cubierta/ducto de polietileno) se clasifica como ductil -> K = 0.3.
   No existe una curva estandar especifica para fibra optica; la literatura usa
   la de lineas enterradas (ver README). Se aplica el MISMO modelo a todos los
   enlaces (fibra, postacion, camino, ferry, puentes y accesos).

4) Probabilidad de falla del enlace (Poisson a lo largo del cable, integrado en
   sub-tramos de ~1 km):
       P_f = 1 - exp( - sum_i RR_i * L_i )

Modelos alternativos (solo para el test de sensibilidad, sensibilidad.py):
   hazus_fragil : HAZUS con K = 1.0
   ala2001      : American Lifelines Alliance (2001), RR = K1 * 0.00187 * PGV[in/s]
                  por 1000 ft, con K1 = 1.0 (valor base de la relacion)
"""
import math
from collections import defaultdict

MODELO_PRINCIPAL = "hazus_ductil"


def rr_hazus(pgv_cms, k):
    return k * 0.0001 * pgv_cms ** 2.25


def rr_ala2001(pgv_cms, k1):
    # 0.00187 rep/1000ft por in/s  ->  /0.3048 km, /2.54 cm/s  = 0.002416 rep/km por cm/s
    return k1 * 0.002416 * pgv_cms


MODELOS = {
    "hazus_ductil": {"desc": "HAZUS / O'Rourke & Ayala (1993), ductil K=0.3",
                     "rr": lambda pgv: rr_hazus(pgv, 0.3)},
    "hazus_fragil": {"desc": "HAZUS / O'Rourke & Ayala (1993), fragil K=1.0",
                     "rr": lambda pgv: rr_hazus(pgv, 1.0)},
    "ala2001":      {"desc": "ALA (2001), K1=1.0",
                     "rr": lambda pgv: rr_ala2001(pgv, 1.0)},
}


def pga_youngs97(m, r_hipo_km, h_km):
    ln_pga = (0.2418 + 1.414 * m
              - 2.552 * math.log(r_hipo_km + 1.7818 * math.exp(0.554 * m))
              + 0.00607 * h_km)
    return math.exp(ln_pga)


def pgv_desde_pga(pga_g):
    return 121.9 * pga_g


SQL_SUBTRAMOS = """
WITH s AS (SELECT geom FROM sismo WHERE usgs_id = %s)
SELECT e.id, e.tipo, e.largo_km,
       ST_Length(d.geom::geography) / 1000.0                                          AS l_km,
       ST_Distance(ST_LineInterpolatePoint(d.geom, 0.5)::geography, s.geom::geography)
         / 1000.0                                                                      AS repi_km
FROM enlaces e CROSS JOIN s
CROSS JOIN LATERAL ST_DumpSegments(ST_Segmentize(e.geom::geography, 1000)::geometry) d
"""


def cargar_subtramos(cur):
    """Devuelve (sismo, subtramos) con subtramos = [(id, tipo, largo, l_km, pga, pgv)]."""
    cur.execute("SELECT usgs_id, magnitud, profundidad_km, lugar FROM sismo "
                "WHERE magnitud >= 8.8 ORDER BY magnitud DESC LIMIT 1")
    usgs_id, mag, h, lugar = cur.fetchone()
    cur.execute(SQL_SUBTRAMOS, (usgs_id,))
    sub = []
    for eid, tipo, largo, l_km, repi in cur.fetchall():
        pga = pga_youngs97(mag, math.hypot(repi, h), h)
        sub.append((eid, tipo, largo, l_km, repi, pga, pgv_desde_pga(pga)))
    sismo = {"usgs_id": usgs_id, "magnitud": mag, "profundidad_km": h, "lugar": lugar}
    return sismo, sub


def probabilidades(sub, modelo=MODELO_PRINCIPAL):
    """P_f por enlace segun el modelo indicado."""
    rr = MODELOS[modelo]["rr"]
    acc = defaultdict(lambda: {"lambda": 0.0, "repi_min": 1e9, "pga_max": 0.0, "tipo": None, "largo": 0})
    for eid, tipo, largo, l_km, repi, pga, pgv in sub:
        a = acc[eid]
        a["tipo"], a["largo"] = tipo, largo
        a["lambda"] += rr(pgv) * l_km
        a["repi_min"] = min(a["repi_min"], repi)
        a["pga_max"] = max(a["pga_max"], pga)
    return {
        eid: {
            "tipo": a["tipo"],
            "largo_km": a["largo"],
            "dist_epi_min_km": a["repi_min"],
            "pga_max_g": a["pga_max"],
            "pgv_max_cms": pgv_desde_pga(a["pga_max"]),
            "n_reparaciones_esp": a["lambda"],
            "p_falla": 1.0 - math.exp(-a["lambda"]),
        }
        for eid, a in acc.items()
    }


def calcular(cur):
    sismo, sub = cargar_subtramos(cur)
    return sismo, probabilidades(sub, MODELO_PRINCIPAL)


def escribir_sql_probabilidades(path, sismo, res):
    """Escribe el SQL que crea prob_falla y actualiza enlaces.p_falla (se aplica
    a la BD en run.py). main.sql (dump completo) lo genera main.py con pg_dump."""
    def f(x):
        return "NULL" if x is None else f"{x:.17g}"

    lineas = [
        "-- =====================================================================",
        "-- prob_falla.sql : probabilidad de falla de cada enlace producto del sismo",
        f"-- Sismo: {sismo['lugar']} ({sismo['usgs_id']}) M{sismo['magnitud']}, "
        f"H={sismo['profundidad_km']} km",
        "-- Modelo: PGA Youngs et al. (1997) interfase/roca desde el epicentro,",
        "--         PGV = 121.9*PGA (Newmark & Hall 1982, suelo competente: 48 in/s/g),",
        "--         RR = 0.3 * 0.0001 * PGV^2.25 [rep/km] (HAZUS / O'Rourke & Ayala 1993, ductil),",
        "--         P_f = 1 - exp(-sum RR*L)",
        "-- Generado por analysis/fallas.py",
        "-- =====================================================================",
        "BEGIN;",
        "DROP TABLE IF EXISTS prob_falla CASCADE;",
        "CREATE TABLE prob_falla (",
        "    enlace_id          integer PRIMARY KEY REFERENCES enlaces(id),",
        "    tipo               text,",
        "    largo_km           double precision,",
        "    dist_epi_min_km    double precision,",
        "    pga_max_g          double precision,",
        "    pgv_max_cms        double precision,",
        "    n_reparaciones_esp double precision,",
        "    p_falla            double precision",
        ");",
    ]
    ids = sorted(res)
    for i in range(0, len(ids), 500):
        lineas.append("INSERT INTO prob_falla VALUES")
        vals = []
        for eid in ids[i:i + 500]:
            r = res[eid]
            vals.append(f"({eid},'{r['tipo']}',{f(r['largo_km'])},"
                        f"{f(r['dist_epi_min_km'])},{f(r['pga_max_g'])},{f(r['pgv_max_cms'])},"
                        f"{f(r['n_reparaciones_esp'])},{f(r['p_falla'])})")
        lineas.append(",\n".join(vals) + ";")
    lineas += [
        "UPDATE enlaces e SET p_falla = p.p_falla FROM prob_falla p WHERE p.enlace_id = e.id;",
        "COMMIT;",
        "",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lineas))
