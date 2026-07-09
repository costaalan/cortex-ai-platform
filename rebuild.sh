#!/bin/bash
# Build cortex-api with CPU-only PyTorch
cd /opt/data/cortex
echo "=== Cortex API Rebuild $(date) ==="
docker compose build --no-cache cortex-api 2>&1
echo "=== Build done: $? ==="
docker images cortex-cortex-api --format "table {{.Repository}}\t{{.Size}}\t{{.CreatedAt}}"
docker compose up -d cortex-api 2>&1
sleep 5
curl -s http://localhost:8705/health
