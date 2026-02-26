#!/usr/bin/env bash
set -euo pipefail

REGION_URL="${1:-https://download.geofabrik.de/asia/india-latest.osm.pbf}"
mkdir -p valhalla_data
curl -L "$REGION_URL" -o valhalla_data/region.osm.pbf

docker run --rm \
  -v "$(pwd)/valhalla_data:/data" \
  ghcr.io/valhalla/valhalla:latest \
  bash -lc "valhalla_build_config --mjolnir-tile-dir /data/tiles --mjolnir-tile-extract /data/tiles.tar > /data/valhalla.json && valhalla_build_tiles -c /data/valhalla.json /data/region.osm.pbf"

echo "Tiles ready in ./valhalla_data"
