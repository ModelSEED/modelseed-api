# ModelSEED API — Docker build
#
# Expects all dependency repos cloned as siblings (see README):
#   modelseed/
#     modelseed-api/    (this repo)
#     ModelSEEDpy/      (cshenry fork, main branch)
#     KBUtilLib/        (private, needs kbase org access)
#     ModelSEEDDatabase/ (dev branch)
#     ModelSEEDTemplates/
#     cb_annotation_ontology_api/
#
# Build: cd modelseed && docker compose -f modelseed-api/docker-compose.yml up --build

FROM python:3.11-slim

# System deps for cobra (GLPK solver) and compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    glpk-utils \
    libglpk-dev \
    libexpat1 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency repos (cloned as siblings of modelseed-api)
COPY ModelSEEDpy /deps/ModelSEEDpy
COPY KBUtilLib /deps/KBUtilLib
COPY ModelSEEDDatabase /deps/ModelSEEDDatabase
COPY ModelSEEDTemplates /deps/ModelSEEDTemplates
COPY cb_annotation_ontology_api /deps/cb_annotation_ontology_api

# Install dependency packages
RUN pip install --no-cache-dir -e /deps/ModelSEEDpy && \
    pip install --no-cache-dir -e /deps/KBUtilLib

# Copy and install modelseed-api
COPY modelseed-api/src/ /app/src/
COPY modelseed-api/pyproject.toml /app/
RUN pip install --no-cache-dir -e ".[modeling]"

# Environment configuration
ENV MODELSEED_MODELSEED_DB_PATH=/deps/ModelSEEDDatabase
ENV MODELSEED_TEMPLATES_PATH=/deps/ModelSEEDTemplates/templates/v7.0
ENV MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH=/deps/cb_annotation_ontology_api
ENV MODELSEED_JOB_STORE_DIR=/tmp/modelseed-jobs
ENV MODELSEED_HOST=0.0.0.0
ENV MODELSEED_PORT=8000

EXPOSE 8000

WORKDIR /app/src
CMD ["python", "-m", "uvicorn", "modelseed_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
