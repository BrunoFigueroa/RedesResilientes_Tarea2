-- Carga el GeoJSON de USGS (pasado como variable psql :geojson)
DROP TABLE IF EXISTS sismo CASCADE;
CREATE TABLE sismo (
    usgs_id        text PRIMARY KEY,
    magnitud       double precision,
    lugar          text,
    fecha          timestamptz,
    profundidad_km double precision,
    propiedades    jsonb,
    geom           geometry(Point, 4326)
);

INSERT INTO sismo
SELECT f->>'id',
       (f->'properties'->>'mag')::double precision,
       f->'properties'->>'place',
       to_timestamp((f->'properties'->>'time')::bigint / 1000.0),
       (f->'geometry'->'coordinates'->>2)::double precision,
       f->'properties',
       ST_SetSRID(ST_Force2D(ST_GeomFromGeoJSON(f->>'geometry')), 4326)
FROM jsonb_array_elements((:'geojson')::jsonb -> 'features') f;
