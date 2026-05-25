import { readFile, writeFile, mkdir } from "node:fs/promises";
import { feature } from "topojson-client";

const root = new URL("../", import.meta.url);
const source = new URL("../node_modules/world-atlas/countries-110m.json", import.meta.url);
const target = new URL("../apps/web/public/map/natural-earth/countries-110m.geojson", import.meta.url);

const world = JSON.parse(await readFile(source, "utf8"));
const countries = feature(world, world.objects.countries);

repairAntimeridianFeatures(countries);
dropKnownAntimeridianFragments(countries);
markAntimeridianFeatures(countries);

countries.metadata = {
  source: "Natural Earth Admin 0 country boundaries via world-atlas",
  scale: "1:110m",
  license: "Public domain",
  generated_by: "scripts/build_map_assets.mjs"
};

await mkdir(new URL("./", target), { recursive: true });
await writeFile(target, JSON.stringify(countries));
console.log(`Wrote ${target.pathname.replace(root.pathname, "")}`);

function repairAntimeridianFeatures(collection) {
  for (const item of collection.features ?? []) {
    const repairedGeometry = repairAntimeridianGeometry(item.geometry);
    if (!repairedGeometry) continue;
    item.geometry = repairedGeometry;
    item.properties = item.properties ?? {};
    item.properties.antimeridianRepaired = true;
  }
}

function dropKnownAntimeridianFragments(collection) {
  for (const item of collection.features ?? []) {
    if (item.properties?.name !== "Russia" || item.geometry?.type !== "MultiPolygon") continue;
    const originalCount = item.geometry.coordinates.length;
    const coordinates = item.geometry.coordinates.filter((polygon) => !isWesternAntimeridianFragment(polygon));
    if (coordinates.length === originalCount || coordinates.length === 0) continue;
    item.geometry = { ...item.geometry, coordinates };
    item.properties = item.properties ?? {};
    item.properties.antimeridianFragmentDropped = true;
  }
}

function isWesternAntimeridianFragment(polygon) {
  const bounds = polygonBounds(polygon);
  if (!bounds) return false;
  const [minLng, minLat, maxLng, maxLat] = bounds;
  const width = maxLng - minLng;
  const height = maxLat - minLat;
  return maxLng <= -170 && width <= 20 && height <= 20;
}

function polygonBounds(polygon) {
  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;
  for (const ring of polygon ?? []) {
    for (const point of ring ?? []) {
      const [lng, lat] = point;
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
      minLng = Math.min(minLng, lng);
      minLat = Math.min(minLat, lat);
      maxLng = Math.max(maxLng, lng);
      maxLat = Math.max(maxLat, lat);
    }
  }
  if (!Number.isFinite(minLng)) return null;
  return [minLng, minLat, maxLng, maxLat];
}

function repairAntimeridianGeometry(geometry) {
  if (!geometry?.coordinates) return null;
  if (geometry.type === "Polygon") {
    const polygon = repairPolygon(geometry.coordinates);
    return polygon ? { ...geometry, coordinates: polygon } : null;
  }
  if (geometry.type === "MultiPolygon") {
    let repaired = false;
    const coordinates = geometry.coordinates.map((polygon) => {
      const next = repairPolygon(polygon);
      if (!next) return polygon;
      repaired = true;
      return next;
    });
    return repaired ? { ...geometry, coordinates } : null;
  }
  return null;
}

function repairPolygon(polygon) {
  let repaired = false;
  const rings = polygon.map((ring) => {
    const next = repairRing(ring);
    if (next === ring) return ring;
    repaired = true;
    return next;
  });
  return repaired ? rings : null;
}

function repairRing(ring) {
  const jumps = antimeridianJumpIndexes(ring);
  if (jumps.length !== 2) return ring;
  const [firstJump, secondJump] = jumps;
  const wrappedPointCount = secondJump - firstJump;
  const remainingPointCount = ring.length - wrappedPointCount;
  const repaired =
    wrappedPointCount <= remainingPointCount
      ? [...ring.slice(0, firstJump + 1), ...ring.slice(secondJump + 1)]
      : ring.slice(firstJump + 1, secondJump + 1);
  const closed = closeRing(repaired);
  return closed.length >= 4 ? closed : ring;
}

function antimeridianJumpIndexes(ring) {
  const indexes = [];
  for (let index = 1; index < ring.length; index += 1) {
    if (Math.abs(ring[index][0] - ring[index - 1][0]) > 180) {
      indexes.push(index - 1);
    }
  }
  return indexes;
}

function closeRing(ring) {
  if (ring.length < 4) return ring;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) return ring;
  return [...ring, first];
}

function markAntimeridianFeatures(collection) {
  for (const item of collection.features ?? []) {
    if (!geometryCrossesAntimeridian(item.geometry)) continue;
    item.properties = item.properties ?? {};
    item.properties.crossesAntimeridian = true;
  }
}

function geometryCrossesAntimeridian(geometry) {
  if (!geometry?.coordinates) return false;
  if (geometry.type === "Polygon") {
    return geometry.coordinates.some(ringCrossesAntimeridian);
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.some((polygon) => polygon.some(ringCrossesAntimeridian));
  }
  return false;
}

function ringCrossesAntimeridian(ring) {
  for (let index = 1; index < ring.length; index += 1) {
    if (Math.abs(ring[index][0] - ring[index - 1][0]) > 180) {
      return true;
    }
  }
  return false;
}
