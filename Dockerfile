# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend ./frontend
COPY tsconfig.json vite.config.ts ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 AUTO_SHORTS_DATA=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk gosu ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home shorts \
    && mkdir /data && chown shorts:shorts /data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY assets ./assets
COPY web/covers ./web/covers
COPY templates.json ./
COPY scripts/serve.py scripts/container-entrypoint.sh ./scripts/
COPY --from=frontend /build/dist ./dist
RUN chmod -R a+rX /app
EXPOSE 8080
ENTRYPOINT ["bash", "scripts/container-entrypoint.sh"]
