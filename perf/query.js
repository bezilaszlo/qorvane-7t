import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DURATION = __ENV.DURATION || "30s";
const VUS = parseInt(__ENV.VUS || "8");
const SENSORS = parseInt(__ENV.SENSORS || "10");
const STAT = __ENV.STAT || "avg";
const SECONDS = parseInt(DURATION) + 5;

const CASES = {
  day_single: { days: 1, single: true },
  day_all: { days: 1, single: false },
  d30_single: { days: 30, single: true },
  d30_all: { days: 30, single: false },
};

const scenarios = {};
const thresholds = {};
Object.keys(CASES).forEach((name, idx) => {
  scenarios[name] = {
    executor: "constant-vus",
    vus: VUS,
    duration: DURATION,
    startTime: `${idx * SECONDS}s`,
    exec: "query",
    env: { CASE: name },
    tags: { case: name },
  };
  thresholds[`http_req_duration{case:${name}}`] = ["p(95)>=0"];
  thresholds[`http_req_failed{case:${name}}`] = ["rate>=0"];
  thresholds[`http_reqs{case:${name}}`] = ["count>=0"];
});

export const options = {
  scenarios,
  thresholds,
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"],
};

export function query() {
  const c = CASES[__ENV.CASE];
  const end = new Date();
  const start = new Date(end.getTime() - c.days * 86400 * 1000);
  const params = [
    "metric=temperature",
    "metric=humidity",
    "metric=wind_speed",
    `stat=${STAT}`,
    `start=${start.toISOString()}`,
    `end=${end.toISOString()}`,
  ];
  if (c.single) {
    const n = 1 + Math.floor(Math.random() * SENSORS);
    params.push(`sensor_id=sensor-${String(n).padStart(3, "0")}`);
  }
  const res = http.get(`${BASE_URL}/api/v1/stats?${params.join("&")}`, {
    tags: { case: __ENV.CASE },
  });
  check(res, { "status 200": (r) => r.status === 200 });
}

export function handleSummary(data) {
  const rows = Object.keys(CASES).map((name) => {
    const d = data.metrics[`http_req_duration{case:${name}}`]?.values || {};
    const reqs = data.metrics[`http_reqs{case:${name}}`]?.values.count || 0;
    const failed = data.metrics[`http_req_failed{case:${name}}`]?.values.rate || 0;
    return (
      `RESULT ${name} vus=${VUS} reqs=${reqs} req_per_s=${(reqs / parseInt(DURATION)).toFixed(1)} ` +
      `p50=${d["p(50)"]?.toFixed(1)} p95=${d["p(95)"]?.toFixed(1)} p99=${d["p(99)"]?.toFixed(1)} ` +
      `fail_rate=${failed}`
    );
  });
  return { stdout: rows.join("\n") + "\n" };
}
