"""ATTR de la infraestructura en operacion (sin terremoto).

Verifica la conectividad de todos los nodos clave de dos formas:
  1) pgRouting: pgr_connectedComponents sobre la tabla enlaces
  2) Python: union-find sobre el grafo contraido (sin vertices de grado 2)
"""
from grafo import attr_clave, attr_conjunto, cargar_red, componentes, conectar, contraer


def attr_pgrouting(cur):
    cur.execute("""
        SELECT n.nombre, c.component
        FROM nodos_clave n
        JOIN pgr_connectedComponents(
            'SELECT id, source, target, 1 AS cost, 1 AS reverse_cost FROM enlaces') c
          ON c.node = n.vertice_id
        ORDER BY n.id""")
    filas = cur.fetchall()
    k = len(filas)
    con = sum(1 for i in range(k) for j in range(i + 1, k) if filas[i][1] == filas[j][1])
    return con / (k * (k - 1) / 2), filas


def calcular(cur):
    enlaces, grado, vclave, nodos_clave = cargar_red(cur)
    nodos, logicos = contraer(enlaces, grado, vclave)
    uf = componentes(nodos, [(u, v) for u, v, _ in logicos])

    vert_clave = [n[3] for n in nodos_clave]
    attr_k = attr_clave(uf, vert_clave)
    attr_pgr, filas = attr_pgrouting(cur)
    assert abs(attr_k - attr_pgr) < 1e-12, (attr_k, attr_pgr)

    inter = [v for v, g in grado.items() if g >= 3]
    nodos_red = sorted(set(inter) | vclave)
    return {
        "attr_nodos_clave": attr_k,
        "attr_nodos_red": attr_conjunto(uf, nodos_red),
        "n_nodos_clave": len(vert_clave),
        "n_intersecciones": len(inter),
        "n_nodos_red": len(nodos_red),
        "n_enlaces_segmentos": len(enlaces),
        "n_enlaces_logicos": len(logicos),
        "componentes_nodos_clave": len({c for _, c in filas}),
    }


if __name__ == "__main__":
    with conectar() as conn, conn.cursor() as cur:
        r = calcular(cur)
    for k, v in r.items():
        print(f"{k:28s} {v}")
