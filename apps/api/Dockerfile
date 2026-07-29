FROM python:3.11-slim

# GDAL/GEOS : nécessaires à geopandas et shapely pour les exports SIG
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgdal-dev libgeos-dev gdal-bin curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-full.txt ./
ARG INSTALL_EXTRAS=full
RUN if [ "$INSTALL_EXTRAS" = "full" ]; then \
      pip install --no-cache-dir -r requirements-full.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

COPY pratisig_api ./pratisig_api

ENV PYTHONUNBUFFERED=1 \
    PRATISIG_DATA_DIR=/data \
    PRATISIG_CACHE_DIR=/data/cache

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "pratisig_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
