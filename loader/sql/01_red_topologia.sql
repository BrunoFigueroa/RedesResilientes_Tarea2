-- =====================================================================
-- Red de corredores relevados por Yafun (SUBTEL/NIC 2018):
--   fibra  : fibra optica detectada (aerea, en postes)
--   poste  : postacion electrica sin fibra detectada
--   camino : camino sin postacion (se asume fibra soterrada)
--   ferry  : trayectos en ferry
--   puente : enlace virtual (<= 3 km) que cierra huecos no relevados
--
-- Columna origen / sintetico (enlaces que NO son fibra detectada):
--   detectado : fibra optica vista en terreno (unico tendido confirmado)
--   supuesto  : poste / camino / ferry -> corredor relevado sin fibra visible;
--               Yafun (sec. 6.1, S3) los usa como rutas posibles del grafo
--   sintetico : puente (<= 3 km) y acceso a plaza de armas (S1, 02_nodos_clave.sql)
-- Columna p_falla: probabilidad de falla del enlace, 0 por defecto (en operacion);
--   la actualiza analysis/fallas.py con el modelo del sismo (queda en main.sql).
-- =====================================================================
DROP TABLE IF EXISTS enlaces_in, enlaces_in_noded, enlaces, enlaces_vertices_pgr CASCADE;

-- 1) Todas las capas en una tabla de entrada
CREATE TABLE enlaces_in (
    id    serial PRIMARY KEY,
    tipo  text NOT NULL,
    id_original text,
    geom  geometry(LineString, 4326)
);
INSERT INTO enlaces_in (tipo, id_original, geom)
SELECT 'fibra',  id::text, (ST_Dump(ST_Force2D(geom))).geom FROM raw_fibra_optica_detectada      UNION ALL
SELECT 'ferry',  id::text, (ST_Dump(ST_Force2D(geom))).geom FROM raw_trayecto_en_ferry           UNION ALL
SELECT 'poste',  id::text, (ST_Dump(ST_Force2D(geom))).geom FROM raw_postacion_electrica_detectada UNION ALL
SELECT 'camino', id::text, (ST_Dump(ST_Force2D(geom))).geom FROM raw_camino_sin_postacion_detectado;
DELETE FROM enlaces_in WHERE ST_Length(geom) = 0;
CREATE INDEX ON enlaces_in USING gist (geom);

-- 2) Partir tramos donde se cruzan (cruces en T / X a mitad de linea)
SELECT pgr_nodeNetwork('enlaces_in', 0.001, 'id', 'geom');

-- 3) Tabla final de enlaces
CREATE TABLE enlaces (
    id          serial PRIMARY KEY,
    tipo        text NOT NULL,
    id_original text,
    in_id       integer,
    largo_km    double precision,
    source      integer,
    target      integer,
    origen      text,
    sintetico   boolean NOT NULL DEFAULT false,
    p_falla     double precision NOT NULL DEFAULT 0
                CHECK (p_falla >= 0 AND p_falla <= 1),
    geom        geometry(LineString, 4326)
);
INSERT INTO enlaces (tipo, id_original, in_id, geom)
SELECT i.tipo, i.id_original, i.id, n.geom
FROM enlaces_in_noded n JOIN enlaces_in i ON i.id = n.old_id
WHERE ST_GeometryType(n.geom) = 'ST_LineString';
UPDATE enlaces SET largo_km = ST_Length(geom::geography) / 1000.0;
DELETE FROM enlaces WHERE largo_km = 0;
UPDATE enlaces SET origen = CASE WHEN tipo = 'fibra' THEN 'detectado' ELSE 'supuesto' END,
                   sintetico = (tipo <> 'fibra');
CREATE INDEX enlaces_geom_idx ON enlaces USING gist (geom);

-- 4) Topologia (tolerancia 0.001 grados ~ 100 m): une extremos digitalizados
--    que casi se tocan; se muestran los NOTICE de pgRouting como evidencia.
SET client_min_messages = notice;
SELECT pgr_createTopology('enlaces', 0.001, 'geom', 'id', 'source', 'target', clean := true);
SET client_min_messages = warning;
CREATE INDEX ON enlaces (source);
CREATE INDEX ON enlaces (target);
CREATE INDEX ON enlaces_vertices_pgr USING gist (the_geom);

-- 5) Enlaces puente: une componentes desconectadas por el hueco mas corto (<= 3 km),
--    de a uno, hasta que no queden huecos <= 3 km.
DO $$
DECLARE
    r record;
    n int := 0;
BEGIN
    LOOP
        DROP TABLE IF EXISTS tmp_comp;
        CREATE TEMP TABLE tmp_comp AS
        SELECT node, component FROM pgr_connectedComponents(
            'SELECT id, source, target, 1 AS cost, 1 AS reverse_cost FROM enlaces');
        CREATE INDEX ON tmp_comp (node);

        SELECT a.id AS va, b.id AS vb, a.the_geom AS ga, b.the_geom AS gb,
               ST_Distance(a.the_geom::geography, b.the_geom::geography) AS m
        INTO r
        FROM enlaces_vertices_pgr a
        JOIN tmp_comp ca ON ca.node = a.id
        CROSS JOIN LATERAL (
            SELECT w.id, w.the_geom FROM enlaces_vertices_pgr w
            JOIN tmp_comp cw ON cw.node = w.id
            WHERE cw.component <> ca.component
              AND ST_DWithin(w.the_geom, a.the_geom, 0.04)
            ORDER BY w.the_geom <-> a.the_geom LIMIT 1
        ) b
        ORDER BY m LIMIT 1;

        EXIT WHEN r IS NULL OR r.m > 3000;

        INSERT INTO enlaces (tipo, origen, sintetico, largo_km, source, target, geom)
        VALUES ('puente', 'sintetico', true, r.m / 1000.0, r.va, r.vb, ST_MakeLine(r.ga, r.gb));
        n := n + 1;
    END LOOP;
    RAISE WARNING 'Enlaces puente agregados: %', n;
END $$;
