import http from "k6/http";
import exec from "k6/execution";
import { Counter } from "k6/metrics";
import { BASE_URL, record, sweep, summarize } from "./lib.js";

const BATCH = parseInt(__ENV.BATCH || "1");
const METRICS = ["temperature", "humidity", "wind_speed"];

const points = new Counter("points_sent");

export const options = sweep("ingest", ["points_sent"]);

export function setup() {
  return { runId: Date.now().toString(36), t0: Date.now() - 24 * 3600 * 1000 };
}

// Each VU writes its own sensor id with unique timestamps, so no insert is a duplicate.
export function ingest(data) {
  const sensor = `perf-${data.runId}-${exec.scenario.name}-${exec.vu.idInTest}`;
  const base = data.t0 + exec.vu.iterationInScenario * BATCH;
  const readings = [];
  for (let i = 0; i < BATCH; i++) {
    const m = {};
    for (const name of METRICS) m[name] = 10 + Math.random() * 20;
    readings.push({ sensor_id: sensor, ts: new Date(base + i).toISOString(), metrics: m });
  }
  const res = http.post(`${BASE_URL}/api/v1/readings`, JSON.stringify({ readings }), {
    headers: { "Content-Type": "application/json" },
  });
  if (record(res)) points.add(BATCH * METRICS.length);
}

export function handleSummary(data) {
  return summarize(data, `batch${BATCH}`, "points_sent");
}
