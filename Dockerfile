FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements-backend.txt .
RUN pip install --no-cache-dir --user -r requirements-backend.txt

FROM python:3.11-slim AS runtime

RUN groupadd -r appgroup && useradd -r -m -g appgroup appuser

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --chown=appuser:appgroup --from=builder /root/.local /home/appuser/.local

COPY --chown=appuser:appgroup . .

ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000

RUN mkdir -p /app/workspace/repos && \
    chown -R appuser:appgroup /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]