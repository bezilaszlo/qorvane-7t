import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";
import exec from "k6/execution";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DURATION = __ENV.DURATION || "30s";
const VUS = parseInt(__ENV.VUS || "16");
const METRICS = ["temperature", "humidity", "wind_speed"];
const BATCHES = { batch1: 1, batch500: 500 };
const SECONDS = parseInt(DURATION) + 5;

const points = new Counter("points_sent");

function scenario(name, startTime) {
  return {
    executor: "constant-vus",
    vus: VUS,
    duration: DURATION,
    startTime,
    exec: "ingest",
    env: { BATCH: String(BATCHES[name]) },
    tags: { batch: name },
  };
}

const thresholds = {};
for (const name of Object.keys(BATCHES)) {
  thresholds[`http_req_duration{batch:${name}}`] = ["p(95)>=0"];
  thresholds[`http_req_failed{batch:${name}}`] = ["rate>=0"];
  thresholds[`points_sent{batch:${name}}`] = ["count>=0"];
  thresholds[`http_reqs{batch:${name}}`] = ["count>=0"];
}

export const options = {
  scenarios: {
    batch1: scenario("batch1", "0s"),
    batch500: scenario("batch500", `${SECONDS}s`),
  },
  thresholds,
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"],
};

export function setup() {
  return { runId: Date.now().toString(36), t0: Date.now() - 24 * 3600 * 1000 };
}

export function ingest(data) {
  const batch = parseInt(__ENV.BATCH);
  const sensor = `perf-${data.runId}-${exec.scenario.name}-${exec.vu.idInTest}`;
  const base = data.t0 + exec.vu.iterationInScenario * batch;
  const readings = [];
  for (let i = 0; i < batch; i++) {
    const m = {};
    for (const name of METRICS) m[name] = 10 + Math.random() * 20;
    const ts = new Date(base + i).toISOString();
    readings.push({ sensor_id: sensor, ts, metrics: m });
  }
  const res = http.post(`${BASE_URL}/api/v1/readings`, JSON.stringify({ readings }), {
    headers: { "Content-Type": "application/json" },
    tags: { batch: `batch${batch}` },
  });
  const ok = check(res, { "status 201": (r) => r.status === 201 });
  if (ok) points.add(batch * METRICS.length, { batch: `batch${batch}` });
}

export function handleSummary(data) {
  const rows = [];
  for (const name of Object.keys(BATCHES)) {
    const d = data.metrics[`http_req_duration{batch:${name}}`]?.values || {};
    const pts = data.metrics[`points_sent{batch:${name}}`]?.values.count || 0;
    const failed = data.metrics[`http_req_failed{batch:${name}}`]?.values.rate || 0;
    const reqs = data.metrics[`http_reqs{batch:${name}}`]?.values.count || 0;
    rows.push(
      `RESULT ${name} vus=${VUS} reqs=${reqs} rows_per_s=${(pts / parseInt(DURATION)).toFixed(0)} ` +
        `req_per_s=${(reqs / parseInt(DURATION)).toFixed(1)} p50=${d["p(50)"]?.toFixed(1)} ` +
        `p95=${d["p(95)"]?.toFixed(1)} p99=${d["p(99)"]?.toFixed(1)} fail_rate=${failed}`,
    );
  }
  return { stdout: rows.join("\n") + "\n" };
}
