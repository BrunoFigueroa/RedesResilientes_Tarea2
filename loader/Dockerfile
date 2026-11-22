# Cliente: psql + shp2pgsql (paquete postgis de Debian)
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client postgis \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /loader
COPY load.sh .
COPY sql/ sql/
RUN chmod +x load.sh
ENTRYPOINT ["/loader/load.sh"]
