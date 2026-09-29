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
# This sibling-checkout image is used by the hosted deployment definition in
# the private operations repository. Public users should use
# Dockerfile.standalone or the root docker-compose.yml instead.

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
RUN pip install --no-cache-dir -e ".[modeling,celery]"

# KBUtilLib's current dependency-manager fallback searches beside the Python
# installation even when an explicit ontology path is supplied.
RUN ln -s /deps/cb_annotation_ontology_api /usr/local/lib/python3.11/cb_annotation_ontology_api

# Keep the classifier runtime compatible with ModelSEEDpy's pinned sklearn.
# Then verify KBUtilLib can resolve ontology data and pre-download the classifier.
RUN pip install --no-cache-dir --force-reinstall "numpy<2" "scikit-learn==1.2.0" && \
    python -c "from kbutillib import BVBRCUtils; BVBRCUtils(config_file=False, token_file=None, kbase_token_file=None, token={'patric': 'unused', 'kbase': 'unused'})" && \
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
