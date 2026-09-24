# One image: the React build served by the FastAPI app, same origin, no CORS.

# ---- Web build ----
FROM node:22-slim AS web
WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# ---- API runtime ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app/apps/api
COPY apps/api/requirements.txt ./
RUN pip install -r requirements.txt

COPY apps/api/bioverse ./bioverse
# main.py serves ../web/dist when it exists.
COPY --from=web /build/dist /app/apps/web/dist

RUN useradd --create-home --uid 10001 bioverse
USER bioverse

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn bioverse.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
