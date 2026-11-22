-- =====================================================================
-- Nodos clave: generan, intercambian y reciben informacion.
--
-- Criterio (Yafun 2018, sec. 6.1 y supuesto S1): el nodo de una comuna se
-- ubica en su PLAZA DE ARMAS y el tendido mas cercano se extiende hasta
-- ella "con su mismo tipo de conexion". Aqui:
--   1) se busca el punto P mas cercano de la red a la plaza;
--   2) si P cae a mitad de un enlace, ese enlace se divide en P (nuevo vertice);
--   3) se agrega un ENLACE DE ACCESO plaza -> P del mismo tipo que el tendido.
--
--   genera / intercambia : Santiago (centro, IXP/PIT) y Quilicura (data centers)
--   amarre              : comunas con amarre de cables submarinos
--                         (SUBTEL en Yafun sec. 4.1: salida internacional por
--                          cables submarinos; FOA = Fibra Optica Austral, S11)
--   recibe              : capitales regionales
-- =====================================================================
DROP TABLE IF EXISTS nodos_clave CASCADE;
CREATE TABLE nodos_clave (
    id            serial PRIMARY KEY,
    nombre        text NOT NULL,
    comuna        text NOT NULL,
    rol           text NOT NULL,
    geom          geometry(Point, 4326) NOT NULL,   -- plaza de armas
    vertice_id    integer,                           -- vertice propio del nodo
    largo_acceso_km double precision
);

INSERT INTO nodos_clave (nombre, comuna, rol, geom) VALUES
 ('Santiago - IXP (PIT)',               'Santiago',       'intercambia', ST_SetSRID(ST_MakePoint(-70.6505, -33.4378), 4326)),
 ('Quilicura - data centers',           'Quilicura',      'genera',      ST_SetSRID(ST_MakePoint(-70.7286, -33.3633), 4326)),
 ('Arica - amarre cable submarino',     'Arica',          'amarre',      ST_SetSRID(ST_MakePoint(-70.3209, -18.4786), 4326)),
 ('Valparaiso - amarre cables submarinos','Valparaiso',   'amarre',      ST_SetSRID(ST_MakePoint(-71.6273, -33.0393), 4326)),
 ('Puerto Montt - amarre FOA',          'Puerto Montt',   'amarre',      ST_SetSRID(ST_MakePoint(-72.9396, -41.4718), 4326)),
 ('Caleta Tortel - amarre FOA',         'Tortel',         'amarre',      ST_SetSRID(ST_MakePoint(-73.5350, -47.7960), 4326)),
 ('Punta Arenas - amarre FOA',          'Punta Arenas',   'amarre',      ST_SetSRID(ST_MakePoint(-70.9081, -53.1626), 4326)),
 ('Puerto Williams - amarre FOA',       'Cabo de Hornos', 'amarre',      ST_SetSRID(ST_MakePoint(-67.6047, -54.9346), 4326)),
 ('Iquique',      'Iquique',      'recibe', ST_SetSRID(ST_MakePoint(-70.1521, -20.2142), 4326)),
 ('Antofagasta',  'Antofagasta',  'recibe', ST_SetSRID(ST_MakePoint(-70.3979, -23.6464), 4326)),
 ('Copiapo',      'Copiapo',      'recibe', ST_SetSRID(ST_MakePoint(-70.3322, -27.3665), 4326)),
 ('La Serena',    'La Serena',    'recibe', ST_SetSRID(ST_MakePoint(-71.2519, -29.9027), 4326)),
 ('Rancagua',     'Rancagua',     'recibe', ST_SetSRID(ST_MakePoint(-70.7406, -34.1701), 4326)),
 ('Talca',        'Talca',        'recibe', ST_SetSRID(ST_MakePoint(-71.6660, -35.4270), 4326)),
 ('Chillan',      'Chillan',      'recibe', ST_SetSRID(ST_MakePoint(-72.1033, -36.6067), 4326)),
 ('Concepcion',   'Concepcion',   'recibe', ST_SetSRID(ST_MakePoint(-73.0503, -36.8270), 4326)),
 ('Temuco',       'Temuco',       'recibe', ST_SetSRID(ST_MakePoint(-72.5904, -38.7390), 4326)),
 ('Valdivia',     'Valdivia',     'recibe', ST_SetSRID(ST_MakePoint(-73.2459, -39.8143), 4326)),
 ('Coyhaique',    'Coyhaique',    'recibe', ST_SetSRID(ST_MakePoint(-72.0685, -45.5712), 4326));

ALTER TABLE enlaces ADD COLUMN IF NOT EXISTS acceso boolean NOT NULL DEFAULT false;

DO $$
DECLARE
    n record; e record;
    tol   constant float8 := 0.001;        -- misma tolerancia que pgr_createTopology
    f float8; p geometry; v_p integer; v_n integer; e2 integer;
BEGIN
    FOR n IN SELECT * FROM nodos_clave ORDER BY id LOOP
        -- enlace mas cercano a la plaza (sin contar accesos ya creados)
        SELECT * INTO e FROM enlaces WHERE NOT acceso
        ORDER BY geom <-> n.geom LIMIT 1;
        f := ST_LineLocatePoint(e.geom, n.geom);
        p := ST_LineInterpolatePoint(e.geom, f);

        -- vertice en P: extremo existente o division del enlace
        IF ST_DWithin(p, ST_StartPoint(e.geom), tol) THEN
            v_p := e.source;
        ELSIF ST_DWithin(p, ST_EndPoint(e.geom), tol) THEN
            v_p := e.target;
        ELSE
            INSERT INTO enlaces_vertices_pgr (id, the_geom)
            VALUES ((SELECT max(id) + 1 FROM enlaces_vertices_pgr), p) RETURNING id INTO v_p;
            INSERT INTO enlaces (tipo, id_original, in_id, origen, sintetico, source, target, geom)
            VALUES (e.tipo, e.id_original, e.in_id, e.origen, e.sintetico, v_p, e.target,
                    ST_LineSubstring(e.geom, f, 1))
            RETURNING id INTO e2;
            UPDATE enlaces SET target = v_p, geom = ST_LineSubstring(e.geom, 0, f) WHERE id = e.id;
            UPDATE enlaces SET largo_km = ST_Length(geom::geography) / 1000.0 WHERE id IN (e.id, e2);
        END IF;

        -- vertice propio del nodo (plaza) + enlace de acceso del mismo tipo
        IF ST_DWithin(n.geom, p, tol / 100) THEN
            v_n := v_p;
            UPDATE nodos_clave SET vertice_id = v_n, largo_acceso_km = 0 WHERE id = n.id;
        ELSE
            INSERT INTO enlaces_vertices_pgr (id, the_geom)
            VALUES ((SELECT max(id) + 1 FROM enlaces_vertices_pgr), n.geom) RETURNING id INTO v_n;
            INSERT INTO enlaces (tipo, acceso, origen, sintetico, source, target, geom, largo_km)
            VALUES (e.tipo, true, 'sintetico', true, v_n, v_p, ST_MakeLine(n.geom, p),
                    ST_Distance(n.geom::geography, p::geography) / 1000.0);
            UPDATE nodos_clave SET vertice_id = v_n,
                   largo_acceso_km = ST_Distance(n.geom::geography, p::geography) / 1000.0
            WHERE id = n.id;
        END IF;
    END LOOP;
END $$;

ALTER TABLE enlaces_vertices_pgr ADD COLUMN IF NOT EXISTS es_clave boolean DEFAULT false;
UPDATE enlaces_vertices_pgr SET es_clave = (id IN (SELECT vertice_id FROM nodos_clave));
