FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build

WORKDIR /app

ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.6-alpine@sha256:26b0bf6fbf07297983cb341998d79c831508787de26627dd2a112321b9c3a4af

USER root
RUN apk upgrade --no-cache libcrypto3 libexpat libssl3 libuuid curl libcurl pcre2 zlib nghttp2-libs libpng
USER 101

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY upstream.prod.conf /etc/nginx/semantix-upstream.conf
COPY host-proxy.disabled.conf /etc/nginx/host-proxy.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1
