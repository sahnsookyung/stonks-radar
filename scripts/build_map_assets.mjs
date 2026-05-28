import { readFile, writeFile, mkdir } from "node:fs/promises";
import { feature } from "topojson-client";

const root = new URL("../", import.meta.url);
const source = new URL("../node_modules/world-atlas/countries-110m.json", import.meta.url);
const target = new URL("../apps/web/public/map/natural-earth/countries-110m.geojson", import.meta.url);

const world = JSON.parse(await readFile(source, "utf8"));
const countries = feature(world, world.objects.countries);
const ANTIMERIDIAN_EPSILON = 0.001;

splitAntimeridianFeatures(countries);
markAntimeridianFeatures(countries);
markAntimeridianHoverUnsafeFeatures(countries);

countries.metadata = {
  source: "Natural Earth Admin 0 country boundaries via world-atlas",
  scale: "1:110m",
  license: "Public domain",
  generated_by: "scripts/build_map_assets.mjs"
};

await mkdir(new URL("./", target), { recursive: true });
await writeFile(target, JSON.stringify(countries));
console.log(`Wrote ${target.pathname.replace(root.pathname, "")}`);

function splitAntimeridianFeatures(collection) {
  for (const item of collection.features ?? []) {
    const repairedGeometry = splitAntimeridianGeometry(item.geometry);
    if (!repairedGeometry) continue;
    item.geometry = insetAntimeridianGeometry(repairedGeometry);
    item.properties = item.properties ?? {};
    item.properties.antimeridianSplit = true;
  }
}

function insetAntimeridianGeometry(geometry) {
  return {
    ...geometry,
    coordinates: insetAntimeridianCoordinates(geometry.coordinates)
  };
}

function insetAntimeridianCoordinates(value) {
  if (typeof value === "number") {
    if (value === 180 || value === -180) return antimeridianInsetLongitude(value);
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(insetAntimeridianCoordinates);
  }
  return value;
}

function splitAntimeridianGeometry(geometry) {
  if (!geometry?.coordinates) return null;
  if (geometry.type === "Polygon") {
    const polygons = splitPolygon(geometry.coordinates);
    if (!polygons) return null;
    return polygons.length === 1
      ? { ...geometry, coordinates: polygons[0] }
      : { ...geometry, type: "MultiPolygon", coordinates: polygons };
  }
  if (geometry.type === "MultiPolygon") {
    let repaired = false;
    const coordinates = [];
    for (const polygon of geometry.coordinates) {
      const polygons = splitPolygon(polygon);
      if (!polygons) {
        coordinates.push(polygon);
        continue;
      }
      repaired = true;
      coordinates.push(...polygons);
    }
    return repaired ? { ...geometry, coordinates } : null;
  }
  return null;
}

function splitPolygon(polygon) {
  if (polygon.length !== 1) return null;
  const rings = splitRing(polygon[0]);
  return rings ? rings.map((ring) => [ring]) : null;
}

function splitRing(ring) {
  const jumps = antimeridianJumps(ring);
  if (jumps.length !== 2) return null;
  const [firstJump, secondJump] = jumps;
  const firstSegment = completeAntimeridianSegment(
    ring.slice(firstJump.nextIndex, secondJump.index + 1),
    firstJump.from,
    secondJump.to,
    secondJump.from,
    firstJump.to
  );
  const secondSegment = completeAntimeridianSegment(
    [...ring.slice(secondJump.nextIndex), ...ring.slice(0, firstJump.index + 1)],
    secondJump.from,
    firstJump.to,
    firstJump.from,
    secondJump.to
  );
  const rings = [firstSegment, secondSegment].filter((candidate) => candidate.length >= 4);
  return rings.length >= 2 ? rings : null;
}

function antimeridianJumps(ring) {
  const indexes = [];
  for (let index = 1; index < ring.length; index += 1) {
    if (Math.abs(ring[index][0] - ring[index - 1][0]) > 180) {
      indexes.push({
        index: index - 1,
        nextIndex: index,
        from: ring[index - 1],
        to: ring[index]
      });
    }
  }
  return indexes;
}

function completeAntimeridianSegment(segment, segmentEnd, segmentStart, boundaryStart, boundaryEnd) {
  const sideLongitude = antimeridianInsetLongitude(dominantSideLongitude(segment));
  return closeRing(
    dedupeConsecutivePoints([
      ...segment,
      [sideLongitude, boundaryStart[1]],
      [sideLongitude, boundaryEnd[1]],
      [sideLongitude, segmentStart[1]],
      [sideLongitude, segmentEnd[1]]
    ])
  );
}

function dominantSideLongitude(points) {
  const sum = points.reduce((total, [longitude]) => total + longitude, 0);
  return sum >= 0 ? 180 : -180;
}

function antimeridianInsetLongitude(longitude) {
  return longitude >= 0 ? 180 - ANTIMERIDIAN_EPSILON : -180 + ANTIMERIDIAN_EPSILON;
}

function dedupeConsecutivePoints(ring) {
  const deduped = [];
  for (const point of ring) {
    const previous = deduped.at(-1);
    if (previous && previous[0] === point[0] && previous[1] === point[1]) continue;
    deduped.push(point);
  }
  return deduped;
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

function markAntimeridianHoverUnsafeFeatures(collection) {
  for (const item of collection.features ?? []) {
    if (!item.properties?.crossesAntimeridian) continue;
    item.properties = item.properties ?? {};
    item.properties.antimeridianHoverUnsafe = true;
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
