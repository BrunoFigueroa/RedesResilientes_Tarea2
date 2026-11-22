# Tarea 2 – Resiliencia de la infraestructura de Internet chilena ante el terremoto 8.8

Este repositorio modela la infraestructura documentada en el *Estudio y Recomendaciones sobre la Resiliencia de la Infraestructura de la Internet Chilena* (proyecto **Yafún**, NIC Labs, 2018). Los datos son los de la solicitud de transparencia SUBTEL AN002T0005610. Sobre esa red se calcula el **ATTR** (*Average Two-Terminal Reliability*) entre los nodos clave, antes y después del terremoto **M8.8 del Maule (27-02-2010)**.

## Uso (un solo comando)

Requisitos: **Docker** (con Compose v2) y **Python 3**. No hay que instalar nada más: `main.py` usa solo la biblioteca estándar, y cada etapa corre en su propio contenedor.

```bash
git clone <repo> tarea2 && cd tarea2
python3 main.py            # flujo completo; al final abre el mapa en http://localhost:8080
```

`python3 main.py` hace, en orden:

1. construye las imágenes y levanta PostgreSQL + PostGIS + pgRouting (crea la BD `resiliencia`);
2. obtiene el GeoJSON del sismo desde USGS (usa la copia de `data/sismo/` si ya existe);
3. carga los shapefiles, aplica `pgr_nodeNetwork` y `pgr_createTopology`, define los nodos clave y carga el sismo;
4. calcula el ATTR antes del sismo (`enlaces.p_falla = 0`);
5. calcula la probabilidad de falla de cada enlace y actualiza la BD;
6. calcula el ATTR después del sismo (Monte Carlo sobre `enlaces.p_falla`) y corre los tests;
7. genera **`main.sql`** (dump completo: infraestructura + probabilidades);
8. **carga `main.sql` en una BD vacía** (`resiliencia_check`), recalcula el ATTR y verifica que coincida;
9. levanta el mapa Leaflet.

Otros comandos:

```bash
python3 main.py attr       # recalcula y muestra el ATTR antes / después
python3 main.py verificar  # vuelve a cargar main.sql en una BD vacía y comprueba el ATTR
python3 main.py mapa       # abre el mapa
python3 main.py down       # detiene los contenedores (down --purge borra también la BD)
```

| Variable   | Default | Uso                                 |
|------------|---------|-------------------------------------|
| `DB_PORT`  | 5432    | puerto de PostgreSQL en el host     |
| `WEB_PORT` | 8080    | puerto del mapa                     |
| `MC_ITER`  | 2000    | iteraciones del Monte Carlo         |
| `MC_SEED`  | 42      | semilla (resultados reproducibles)  |

Si ya hay un PostgreSQL local en el puerto 5432: `DB_PORT=5433 python3 main.py`.

### Cargar `main.sql` a mano

`main.sql` carga en cualquier BD vacía con PostGIS y pgRouting instalados (crea las extensiones):

```bash
createdb nueva && psql -d nueva -v ON_ERROR_STOP=1 -f main.sql
```

## Dependencias

| Dónde | Dependencia | Para qué |
|---|---|---|
| host | Docker + Compose v2, Python 3 (stdlib) | `main.py` orquesta los contenedores |
| `db` | imagen `pgrouting/pgrouting:16-3.4-3.6.1` | PostgreSQL 16, PostGIS 3.4, pgRouting 3.6.1 (última serie que trae `pgr_createTopology`) |
| `loader` | Debian `postgresql-client`, `postgis` | `psql` y `shp2pgsql` para cargar los shapefiles |
| `sismo` | Python 3.12 (stdlib) | descarga el GeoJSON de USGS |
| `analysis` | [`analysis/requirements.txt`](analysis/requirements.txt): `psycopg2-binary` | cliente PostgreSQL; el ATTR, el modelo y el Monte Carlo usan solo la stdlib |
| `web` | [`web/requirements.txt`](web/requirements.txt): `psycopg2-binary`, `folium` (instala `branca`) | `folium` genera el mapa Leaflet desde Python; `branca` es la escala de colores de P_f |

## Estructura (un contenedor por función)

```
docker-compose.yml
main.py                 orquestador (stdlib)
main.sql                dump completo: infraestructura + probabilidades de falla (generado)
data/
  Respuesta_T5610/      shapefiles Yafún (SUBTEL)
  sismo/sismo_maule_8.8.geojson   GeoJSON USGS (guardado; no se vuelve a descargar)
db/        PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6.1
sismo/     obtiene el GeoJSON de USGS solo si no existe
loader/    shp2pgsql, pgr_nodeNetwork, pgr_createTopology, nodos clave, intersecciones, sismo
analysis/  ATTR antes, modelo de falla, ATTR después (Monte Carlo), tests, verificar.py
web/       mapa Leaflet (folium) servido en :8080
output/    prob_falla.sql, resultados.json, mapa.html (no versionado)
```

## Tablas principales (también en `main.sql`)

| Tabla | Contenido |
|---|---|
| `enlaces` | segmentos con `source`/`target` de `pgr_createTopology`, `tipo`, `origen`, `sintetico`, `p_falla` (0 por defecto) |
| `enlaces_vertices_pgr` | vértices de `pgr_createTopology` + `grado`, `tipo` (extremo / paso / intersección), `es_clave` |
| `nodos_clave` | 19 nodos clave con rol, plaza de armas y vértice |
| `sismo` | evento USGS `official20100227063411530_30` |
| `prob_falla` | detalle del modelo por enlace: distancia, PGA, PGV, reparaciones esperadas, P_f |
| `resultados_attr`, `conectividad_nodos_clave` | ATTR antes/después y P(conectado al IXP) por nodo |

## Metodología

### 1. Infraestructura → topología
- Se usan las 4 capas de la respuesta SUBTEL (27.523 km): fibra óptica detectada (10.313 km), postación eléctrica, camino sin postación y trayectos en ferry. Yafún (sec. 6.1) también construye su grafo con todas las capas.
- `pgr_nodeNetwork` parte los tramos donde se cruzan. Después, `pgr_createTopology` (tolerancia 0,001° ≈ 100 m) genera `source`/`target` y `enlaces_vertices_pgr`.
- Columna **`p_falla`**: 0 por defecto (red en operación); la actualiza el modelo del sismo.
- Segmentos: 4.838 tras `pgr_createTopology` + 6 puentes + 5 divisiones por nodos clave + 14 accesos = 4.863.
- **Autoloops:** 117 segmentos (5 km) quedan con `source = target` por la tolerancia. No conectan vértices distintos, así que se excluyen del grado (si no, crearían 40 intersecciones falsas) y de las cadenas lógicas; se conservan en la tabla.
- **Enlaces sintéticos** (`sintetico = true`, es decir, *no es fibra detectada*; no significa inventado), marcados en la BD, el informe y el mapa:
  - `origen = 'supuesto'`: postación, camino y ferry (corredores sin fibra visible que Yafún usa como rutas posibles);
  - `origen = 'sintetico'`: 6 **puentes** (11 km, cada uno ≤ 3 km; criterio del supuesto S2 de Yafún) y 14 **accesos** a la plaza de armas (supuesto S1).

### 2. Nodos clave
| Rol | Nodos |
|---|---|
| intercambia | Santiago (PIT Chile / IXP) |
| genera | Quilicura (data centers de Google, Ascenty, etc.) |
| amarre de cables submarinos | Arica y Valparaíso (SAm-1, Curie, etc.); Puerto Montt, Caleta Tortel, Punta Arenas y Puerto Williams (Fibra Óptica Austral) |
| recibe | 11 capitales regionales |

Las intersecciones de grado ≥ 3 son los **nodos troncales** por donde pasa el tráfico. Cada nodo clave se ubica en la plaza de armas de su comuna y se conecta al tendido más cercano (Yafún, supuesto S1). Fuentes en el informe.

### 3. ATTR
ATTR = (1 / C(n,2)) · Σ_{i<j} P(i ↔ j), sobre los n = 19 nodos clave (Colbourn, 1987). P(i ↔ j) es la probabilidad de que i y j queden conectados cuando cada enlace falla con su `p_falla`, leída de la BD.
- Antes del sismo (`p_falla = 0`): cálculo exacto, verificado con `pgr_connectedComponents`.
- Después del sismo: Monte Carlo (2000 iteraciones, semilla 42; el test de convergencia da un IC95 % de ±0,0041).

Como métricas complementarias de ENRN (Alenazi, 2023) se reportan, sobre los nodos de red, la **flow robustness** FR (ec. 8) y **S_LCC** (ec. 7).

### 4. Modelo de falla probabilístico (desde el epicentro)
1. **PGA** según Youngs, Chiou, Silva & Humphrey (1997), subducción interplaca, roca:
   `ln PGA[g] = 0.2418 + 1.414 M − 2.552 ln(R + 1.7818 e^(0.554 M)) + 0.00607 H`, con R = distancia hipocentral (√(R_epi² + H²)), M = 8,8 y H = 22,9 km (USGS).
2. **PGV** según Newmark & Hall (1982), suelo competente: v/a = 48 in/s/g, es decir PGV = 121,9 cm/s por g.
3. **Tasa de reparación** por propagación de ondas, O'Rourke & Ayala (1993) adoptada por **HAZUS (FEMA)**: **RR = K · 0,0001 · PGV^2,25** [rep/km], con K = 0,3 (dúctil, cubierta de polietileno).
4. **Probabilidad de falla** (Poisson), integrada en sub-tramos de 1 km sobre geometría `geography` (metros): **P_f = 1 − exp(−Σ RR_i·L_i)**.

### 5. Tests (`analysis/sensibilidad.py`, `analysis/verificar.py`)
- Sensibilidad al modelo de vulnerabilidad: HAZUS dúctil (principal), HAZUS frágil y ALA (2001).
- Convergencia del Monte Carlo según el número de iteraciones y entre 10 semillas.
- `verificar.py`: `main.sql` cargado en una BD vacía reproduce el mismo ATTR.

## Resultados

| Métrica                         | Antes  | Después (media ± σ) |
|---------------------------------|--------|---------------------|
| ATTR nodos clave (19)           | 1.0000 | **0.3834 ± 0.0943** |
| FR / ATTR nodos de red (648)    | 0.9664 | 0.4033              |
| S_LCC nodos de red (ENRN)       | 0.9830 | 0.4883              |

El ATTR cae en **−0,6166 (−61,7 %)**. Sensibilidad: HAZUS frágil da 0,2717 y ALA (2001) da 0,1212. El sur (de Chillán a Puerto Williams, incluida la FOA) queda conectado al IXP de Santiago en solo ~2 % de las simulaciones; el norte, en ~96 %.

## Limitaciones
- **Datos:** el archivo SAIP trae 10.313 km de fibra detectada, frente a los ~26.500 km recorridos por el Estudio (más ~5.000 km de rutas no validadas, supuesto S4). El 62 % de la red modelada son corredores supuestos. No incluye redes urbanas (Santiago), cables submarinos ni enlaces de microondas o satelitales.
- **Modelo puntual:** se modela desde el epicentro, como pide el enunciado; la ruptura real midió ~500 km.
- **Daños no modelados:** solo sacudimiento. No se modelan las fallas por puentes ni por deformación permanente del suelo, que según TCLEE fueron la principal causa de corte de fibra en 2010, ni la dependencia de la energía eléctrica.

## Referencias
- NIC Labs (2018). *Estudio y Recomendaciones sobre la resiliencia de la infraestructura de la Internet chilena*. Informe técnico final, InnovaChile–CORFO 15BPE-47225.
- Colbourn, C. J. (1987). *The Combinatorics of Network Reliability*. Oxford University Press.
- Alenazi, M. J. F. (2023). ENRN: A System for Evaluating Network Resilience against Natural Disasters. *Mathematics*, 11(20), 4250.
- Youngs, R. R., Chiou, S.-J., Silva, W. J., & Humphrey, J. R. (1997). Strong ground motion attenuation relationships for subduction zone earthquakes. *Seismological Research Letters*, 68(1), 58–73.
- O'Rourke, M. J., & Ayala, G. (1993). Pipeline damage due to wave propagation. *Journal of Geotechnical Engineering*, 119(9).
- FEMA. *Hazus Earthquake Model Technical Manual*.
- American Lifelines Alliance (2001). *Seismic Fragility Formulations for Water Systems*.
- Newmark, N. M., & Hall, W. J. (1982). *Earthquake Spectra and Design*. EERI.
- Kongar, I. et al. (2017). Seismic performance of buried electrical cables. *Bulletin of Earthquake Engineering*, 15.
- TCLEE (2010). *Preliminary report: 27 February 2010 Mw 8.8 offshore Maule, Chile earthquake*. ASCE.
- USGS, evento `official20100227063411530_30`.
