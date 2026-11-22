"""Tests del modelo:

1) Sensibilidad al modelo de vulnerabilidad: ATTR despues del sismo con cada
   relacion de la literatura (HAZUS ductil [principal], HAZUS fragil, ALA 2001).
2) Convergencia del Monte Carlo: ATTR medio y semiancho del IC95 % segun el
   numero de iteraciones, y dispersion entre semillas distintas.
"""
import math
import statistics

import fallas
from montecarlo import simular


def test_modelos(red, sub, iteraciones, semilla):
    out = []
    for nombre, m in fallas.MODELOS.items():
        pf = {eid: r["p_falla"] for eid, r in fallas.probabilidades(sub, nombre).items()}
        r = simular(red, pf, iteraciones, semilla, detalle=True)
        out.append({
            "modelo": nombre,
            "descripcion": m["desc"],
            "p_falla_media_segmentos": sum(pf.values()) / len(pf),
            "attr_nodos_clave": r["attr_nodos_clave"],
            "attr_nodos_clave_std": r["attr_nodos_clave_std"],
            "attr_nodos_red": r["attr_nodos_red"],
            "s_lcc_nodos_red": r["s_lcc_nodos_red"],
        })
    return out


def test_convergencia(red, pf, semilla, niveles=(100, 250, 500, 1000, 2000, 5000), semillas=10):
    serie = simular(red, pf, max(niveles), semilla, detalle=False)["serie"]
    conv = []
    for n in niveles:
        x = serie[:n]
        m = statistics.fmean(x)
        s = statistics.pstdev(x)
        conv.append({"iteraciones": n, "attr_medio": m, "ic95_semiancho": 1.96 * s / math.sqrt(n)})

    n_ref = 2000
    medias = [simular(red, pf, n_ref, semilla + k, detalle=False)["attr_nodos_clave"]
              for k in range(semillas)]
    return {
        "por_iteraciones": conv,
        "entre_semillas": {
            "iteraciones": n_ref, "semillas": semillas,
            "media": statistics.fmean(medias), "desv_std": statistics.pstdev(medias),
            "min": min(medias), "max": max(medias),
        },
    }
