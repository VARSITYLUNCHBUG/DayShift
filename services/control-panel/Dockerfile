# Dev-only control panel: build the SPA with Node, serve it (and proxy the dev APIs) with an
# unprivileged nginx on port 8091. Runs with a read-only root filesystem and a tmpfs on /tmp.

FROM node:26.13.0-trixie-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine3.24
LABEL org.opencontainers.image.title="draft-bot control panel" \
      org.opencontainers.image.description="Dev-only UI for the local stack and the Discord simulator"
ENV NGINX_ENTRYPOINT_QUIET_LOGS=1
COPY nginx.conf /etc/nginx/nginx.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
# The whole server is in nginx.conf; the image's default site would only shadow it.
RUN rm /etc/nginx/conf.d/default.conf && nginx -t
EXPOSE 8091
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8091/healthz"]
