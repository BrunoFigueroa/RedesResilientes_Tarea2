"""Simulacion Monte Carlo de la red tras el sismo.

En cada iteracion cada enlace logico (cadena de segmentos entre nodos reales)
falla con probabilidad 1 - prod(1 - P_f segmento) y se recalculan:
  - ATTR entre nodos clave
  - ATTR / flow robustness entre nodos de red (intersecciones + nodos clave)
  - S_LCC entre nodos de red (ENRN)
  - conectividad de cada nodo clave con el IXP de Santiago
"""
import math
import random

from grafo import UnionFind, attr_clave, attr_conjunto, cargar_red, contraer, s_lcc


class Red:
    def __init__(self, cur):
        self.enlaces, self.grado, vclave, self.nodos_clave = cargar_red(cur)
        self.nodos, self.logicos = contraer(self.enlaces, self.grado, vclave)
        self.vert_clave = [n[3] for n in self.nodos_clave]
        self.nodos_red = sorted({v for v, g in self.grado.items() if g >= 3} | vclave)

    def p_logicos(self, pf):
        return [1.0 - math.prod(1.0 - pf[e] for e in cadena) for _, _, cadena in self.logicos]


def simular(red, pf, iteraciones, semilla, detalle=True):
    p_log = red.p_logicos(pf)
    rng = random.Random(semilla)
    ixp = red.vert_clave[0]
    s_k = s2_k = s_r = s_l = 0.0
    con_ixp = [0] * len(red.vert_clave)
    serie = []
    for _ in range(iteraciones):
        uf = UnionFind(red.nodos)
        for (u, v, _), p in zip(red.logicos, p_log):
            if rng.random() >= p:
                uf.union(u, v)
        a = attr_clave(uf, red.vert_clave)
        serie.append(a)
        s_k += a
        s2_k += a * a
        if detalle:
            s_r += attr_conjunto(uf, red.nodos_red)
            s_l += s_lcc(uf, red.nodos_red)
            r_ixp = uf.find(ixp)
            for i, v in enumerate(red.vert_clave):
                if uf.find(v) == r_ixp:
                    con_ixp[i] += 1

    n = iteraciones
    media = s_k / n
    std = math.sqrt(max(s2_k / n - media ** 2, 0.0))
    res = {
        "attr_nodos_clave": media,
        "attr_nodos_clave_std": std,
        "attr_nodos_clave_ic95": [media - 1.96 * std / math.sqrt(n), media + 1.96 * std / math.sqrt(n)],
        "iteraciones": n,
        "semilla": semilla,
        "p_falla_enlaces_logicos_media": sum(p_log) / len(p_log),
        "serie": serie,
    }
    if detalle:
        res.update({
            "attr_nodos_red": s_r / n,
            "s_lcc_nodos_red": s_l / n,
            "p_conexion_ixp": [
                {"id": k[0], "nombre": k[1], "rol": k[2], "p_conectado_ixp": c / n}
                for k, c in zip(red.nodos_clave, con_ixp)
            ],
        })
    return res
