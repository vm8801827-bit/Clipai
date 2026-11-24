FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/backend/storage/uploads /app/backend/storage/outputs
ENV PYTHONPATH=/app/backend
ENV CLIPAI_STORAGE=/app/backend/storage
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
