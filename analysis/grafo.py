"""Utilidades de grafo: lectura desde la BD, contraccion de lineas segmentadas y ATTR.

ATTR (Average Two-Terminal Reliability) sobre el conjunto de nodos clave K
(Colbourn 1987; Neumayer & Modiano 2010):

    ATTR = 1 / C(|K|, 2) * sum_{i<j in K} P(i <-> j)

P(i <-> j) = probabilidad de que exista un camino operativo entre i y j cuando
cada enlace e falla de forma independiente con probabilidad p_falla(e), leida
de la columna enlaces.p_falla de la BD.
  - En operacion (p_falla = 0 en todos los enlaces) P(i <-> j) es 0 o 1 y el
    ATTR es exacto: (# pares conectados) / C(|K|, 2).
  - Tras el sismo se estima por Monte Carlo (montecarlo.py): promedio, sobre N
    realizaciones del grafo, de la fraccion de pares de K conectados.
"""
from collections import defaultdict

import psycopg2


def conectar():
    return psycopg2.connect("")  # usa PGHOST/PGUSER/PGPASSWORD/PGDATABASE


class UnionFind:
    def __init__(self, nodos):
        self.p = {n: n for n in nodos}

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def cargar_red(cur):
    """Devuelve (enlaces, grado, vertices_clave, nodos_clave).

    enlaces: dict id -> (source, target, tipo, largo_km)
    """
    cur.execute("SELECT id, source, target, tipo, largo_km FROM enlaces ORDER BY id")
    enlaces = {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}
    cur.execute("SELECT id, grado FROM enlaces_vertices_pgr ORDER BY id")
    grado = dict(cur.fetchall())
    cur.execute("SELECT id, nombre, rol, vertice_id FROM nodos_clave ORDER BY id")
    nodos_clave = cur.fetchall()
    return enlaces, grado, {n[3] for n in nodos_clave}, nodos_clave


def cargar_pf(cur):
    """Probabilidad de falla de cada enlace desde la BD: dict id -> p_falla."""
    cur.execute("SELECT id, p_falla FROM enlaces ORDER BY id")
    return {i: float(p) for i, p in cur.fetchall()}


def contraer(enlaces, grado, vertices_clave):
    """Contrae los vertices de grado 2 ('paso'): una linea segmentada pasa a ser
    un solo enlace logico entre nodos reales (intersecciones, extremos o nodos clave).

    Devuelve (nodos, logicos) con logicos = lista de (u, v, [ids de enlaces]).
    """
    nodos = {v for v, g in grado.items() if g != 2} | set(vertices_clave)
    inc = defaultdict(list)
    for eid, (s, t, *_ ) in sorted(enlaces.items()):
        if s == t:      # autoloop: no conecta vertices distintos (ver 03_intersecciones.sql)
            continue
        inc[s].append(eid)
        inc[t].append(eid)

    visit = set()
    logicos = []
    for u in sorted(nodos):   # orden determinista (reproducible desde main.sql)
        for e0 in inc[u]:
            if e0 in visit:
                continue
            visit.add(e0)
            cadena = [e0]
            s, t = enlaces[e0][0], enlaces[e0][1]
            cur_v = t if s == u else s
            while cur_v not in nodos:
                sig = [e for e in inc[cur_v] if e not in visit]
                if not sig:
                    break
                e = sig[0]
                visit.add(e)
                cadena.append(e)
                s, t = enlaces[e][0], enlaces[e][1]
                cur_v = t if s == cur_v else s
            if cur_v != u:
                logicos.append((u, cur_v, cadena))
    return nodos, logicos


def componentes(nodos, aristas):
    uf = UnionFind(nodos)
    for u, v in aristas:
        uf.union(u, v)
    return uf


def attr_clave(uf, vertices_nodos_clave):
    """ATTR entre nodos clave (lista de vertice_id, puede repetir vertices)."""
    k = len(vertices_nodos_clave)
    raices = [uf.find(v) for v in vertices_nodos_clave]
    conectados = sum(1 for i in range(k) for j in range(i + 1, k) if raices[i] == raices[j])
    return conectados / (k * (k - 1) / 2)


def _tamanos(uf, nodos):
    tam = defaultdict(int)
    for n in nodos:
        tam[uf.find(n)] += 1
    return tam.values()


def attr_conjunto(uf, nodos):
    """ATTR sobre un conjunto grande de nodos usando tamanos de componente.
    Equivale a la flow robustness FR(G) de ENRN (Alenazi 2023, ec. 8)."""
    n = len(nodos)
    return sum(s * (s - 1) / 2 for s in _tamanos(uf, nodos)) / (n * (n - 1) / 2)


def s_lcc(uf, nodos):
    """Tamano relativo de la componente conexa mas grande (ENRN, ec. 7)."""
    return max(_tamanos(uf, nodos)) / len(nodos)
