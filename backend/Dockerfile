ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG APP_VERSION=local-unverified
ARG VCS_REF=local
ARG RELEASE_DATE=unknown
LABEL org.opencontainers.image.title="ITOM Backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${RELEASE_DATE}"

WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY release ./release
ENV ITOM_RELEASE_DIR=/srv/release

EXPOSE 6800
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6800"]
