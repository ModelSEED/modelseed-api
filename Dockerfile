# ModelSEED API — Docker build
#
# Expects all dependency repos cloned as siblings (see README):
#   modelseed/
#     modelseed-api/         (this repo)
#     ModelSEEDpy/           (cshenry fork, main branch)
#     KBUtilLib/             (cshenry, main branch)
#     cobrakbase/            (Fxe/cobrakbase, master branch — 0.4.0+)
#     ModelSEEDDatabase/     (dev branch)
#     ModelSEEDTemplates/
#     cb_annotation_ontology_api/
#
# Build: cd modelseed && docker compose -f modelseed-api/docker-compose.yml up --build

FROM python:3.11-slim

# System deps for cobra (GLPK solver), compilation, and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    glpk-utils \
    libglpk-dev \
    libexpat1 \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency repos (cloned as siblings of modelseed-api)
COPY cobrakbase /deps/cobrakbase
COPY ModelSEEDpy /deps/ModelSEEDpy
COPY KBUtilLib /deps/KBUtilLib
COPY ModelSEEDDatabase /deps/ModelSEEDDatabase
COPY ModelSEEDTemplates /deps/ModelSEEDTemplates
COPY cb_annotation_ontology_api /deps/cb_annotation_ontology_api

# Install all Python dependencies from local repos.
# Order matters: cobrakbase first (no deps on others), then ModelSEEDpy, then KBUtilLib.
# All three are installed as editable so container uses the exact cloned versions.
RUN pip install --no-cache-dir -e /deps/cobrakbase && \
    pip install --no-cache-dir -e /deps/ModelSEEDpy && \
    pip install --no-cache-dir -e /deps/KBUtilLib

# Copy and install modelseed-api
COPY modelseed-api/src/ /app/src/
COPY modelseed-api/data/ /app/data/
COPY modelseed-api/pyproject.toml /app/
RUN pip install --no-cache-dir -e ".[modeling]"

# Fix numpy/sklearn binary compatibility (editable installs may pull mismatched versions)
# then pre-download genome classifier files (~25MB) so first model build is fast
RUN pip install --no-cache-dir --force-reinstall numpy scikit-learn && \
    python -c "from modelseedpy.helpers import get_classifier; get_classifier('knn_ACNP_RAST_filter_01_17_2023')"

# Environment configuration
ENV MODELSEED_MODELSEED_DB_PATH=/deps/ModelSEEDDatabase
ENV MODELSEED_TEMPLATES_PATH=/deps/ModelSEEDTemplates/templates/v7.0
ENV MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH=/deps/cb_annotation_ontology_api
ENV MODELSEED_JOB_STORE_DIR=/tmp/modelseed-jobs
ENV MODELSEED_HOST=0.0.0.0
ENV MODELSEED_PORT=8000

# WORKAROUND: cobrakbase.KBaseAPI() reads token from ~/.kbase/token file.
# Required by MSReconstructionUtils init even when not using KBase.
ENV KB_AUTH_TOKEN=unused
RUN mkdir -p /root/.kbase && echo "unused" > /root/.kbase/token

EXPOSE 8000

WORKDIR /app/src
CMD ["python", "-m", "uvicorn", "modelseed_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
