-- Grado de cada vertice = numero de enlaces que llegan a el desde OTRO vertice.
--   grado >= 3 -> interseccion (nodo de la red)
--   grado  = 2 -> 'paso': solo une dos tramos de una misma linea segmentada (NO es nodo)
--   grado  = 1 -> extremo (fin de linea)
--   grado  = 0 -> aislado (solo tiene autoloops)
-- Los autoloops (source = target) se excluyen del grado: son tramos cortos cuyos
-- dos extremos quedaron a menos de la tolerancia (0.001 grados) y pgr_createTopology
-- los asocio al mismo vertice. No conectan vertices distintos, asi que no aportan
-- conectividad; si se contaran, sumarian 2 al grado y crearian intersecciones falsas.
ALTER TABLE enlaces_vertices_pgr
    ADD COLUMN IF NOT EXISTS grado integer,
    ADD COLUMN IF NOT EXISTS tipo  text;

WITH g AS (
    SELECT v, count(*) AS grado
    FROM (SELECT source AS v FROM enlaces WHERE source <> target
          UNION ALL
          SELECT target FROM enlaces WHERE source <> target) x
    GROUP BY v
)
UPDATE enlaces_vertices_pgr p
SET grado = coalesce(g.grado, 0),
    tipo  = CASE WHEN coalesce(g.grado, 0) >= 3 THEN 'interseccion'
                 WHEN g.grado = 2 THEN 'paso'
                 WHEN g.grado = 1 THEN 'extremo'
                 ELSE 'aislado' END
FROM enlaces_vertices_pgr p2 LEFT JOIN g ON g.v = p2.id
WHERE p2.id = p.id;

CREATE OR REPLACE VIEW intersecciones AS
SELECT id, grado, the_geom AS geom FROM enlaces_vertices_pgr WHERE tipo = 'interseccion';
