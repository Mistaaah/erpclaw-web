# Build the SvelteKit frontend, then run it alongside the FastAPI API in one
# Railway service. The API serves the generated static files and owns $PORT.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY src ./src
COPY svelte.config.js vite.config.ts tsconfig.json ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api ./api
COPY scripts ./scripts
COPY --from=frontend-build /app/build ./build

ENV ERPCLAW_WEB_DB=/data/web.sqlite
ENV ERPCLAW_DB=/data/data.sqlite
ENV PORT=8080
EXPOSE 8080

# Railway HTTP logs retain request status/path without exposing query credentials.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
