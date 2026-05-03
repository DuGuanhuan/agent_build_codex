#!/usr/bin/env bash
set -euo pipefail

git pull
docker compose up -d --build
docker image prune -f
docker compose ps
