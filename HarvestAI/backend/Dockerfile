# ─────────────────────────────────────────────────────────────────────────────
# HarvestAI Lambda Container Image
#
# Build context: backend/   (run from repo root: docker build -t harvestai-lambdas backend/)
#
# Uses pre-compiled manylinux wheels. rasterio/shapely/pyproj bundle their own
# GDAL/GEOS/PROJ. rio-tiler and all its runtime deps are installed explicitly.
# ─────────────────────────────────────────────────────────────────────────────

FROM public.ecr.aws/lambda/python:3.11

# ── Upgrade pip ───────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir --upgrade pip

# ── numpy first (other geospatial wheels depend on it at install time) ────────
RUN pip install --no-cache-dir --only-binary=:all: "numpy==1.26.4"

# ── Core geospatial stack (manylinux self-contained wheels) ──────────────────
RUN pip install --no-cache-dir --only-binary=:all: \
    "rasterio==1.3.10" \
    "shapely==2.0.6" \
    "pyproj==3.6.1"

# ── rio-tiler runtime deps (installed before rio-tiler to avoid source builds)
# numexpr and xarray are required at runtime by rio-tiler's COG reader.
RUN pip install --no-cache-dir --only-binary=:all: \
    "numexpr" \
    "xarray" \
    "morecantile==5.4.0" \
    "pydantic>=2.0" \
    "cachetools"

# Install rio-tiler without pulling optional extras that might trigger src builds
RUN pip install --no-cache-dir "rio-tiler==6.6.1"

# ── Runtime dependencies ──────────────────────────────────────────────────────
RUN pip install --no-cache-dir --only-binary=:all: \
    "boto3" \
    "botocore" \
    "requests==2.32.3" \
    "python-dateutil==2.9.0" \
    "Pillow==10.4.0"

RUN pip install --no-cache-dir \
    "python-json-logger==2.0.7" \
    "staticmap==0.5.7"

# ── Lambda function code ──────────────────────────────────────────────────────
COPY lambda_functions/ ${LAMBDA_TASK_ROOT}/lambda_functions/

# ── GDAL / COG tuning (GDAL bundled inside rasterio wheel) ───────────────────
ENV GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
ENV GDAL_HTTP_MULTIPLEX=YES
ENV GDAL_HTTP_VERSION=2
ENV VSI_CACHE=TRUE
ENV VSI_CACHE_SIZE=1000000
ENV CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff,.vrt"

# ── Default handler (overridden per function via Lambda config) ───────────────
CMD ["lambda_functions.daily_batch.handler.handler"]
