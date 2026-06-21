# Stage 1 — build the Vue frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — runtime image
FROM python:3.11-slim
WORKDIR /app

# Install Quarto (required for plotly/static site build format)
ARG QUARTO_VERSION=1.9.38
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${ARCH}.deb" \
         -o /tmp/quarto.deb && \
    dpkg -i /tmp/quarto.deb && \
    rm /tmp/quarto.deb && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Overlay the pre-built frontend from Stage 1 (vite outDir is ../public/app)
COPY --from=frontend-builder /app/public/app ./public/app

# config.json and reports/ are provided at runtime via volume mounts:
#   -v /path/to/config.json:/app/config.json:ro
#   -v /efs/nce-reports:/app/reports

EXPOSE 80

ENTRYPOINT ["python", "NceGitLab.py", "--serve"]
