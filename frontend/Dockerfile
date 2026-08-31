ARG NODE_BASE_IMAGE=node:22-alpine
ARG NGINX_BASE_IMAGE=nginx:1.27-alpine
ARG APP_VERSION=local-unverified
ARG VCS_REF=local
ARG RELEASE_DATE=unknown

FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
COPY release /src/release
RUN npm run build

FROM ${NGINX_BASE_IMAGE}
ARG APP_VERSION
ARG VCS_REF
ARG RELEASE_DATE
LABEL org.opencontainers.image.title="ITOM Frontend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${RELEASE_DATE}"
COPY --from=build /src/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
