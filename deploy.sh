#!/bin/sh
echo "WARN: Deprecated. Use 'make' instead."
git pull
# $1 can be used to add --no-cache if necessary
docker compose build $1
docker compose down
docker compose up -d