import { Counter } from "k6/metrics";

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
export const DURATION = __ENV.DURATION || "15s";
export const WARMUP = __ENV.WARMUP || "10s";
export const LEVELS = (__ENV.LEVELS || "1,2,5,25").split(",").map(Number);

const GAP = 5;
const seconds = (d) => parseInt(d);

export const failed = new Counter("failed_non2xx");
export const shed = new Counter("failed_503");

export function record(res) {
  if (res.status >= 200 && res.status < 300) return true;
  failed.add(1);
  if (res.status === 503) shed.add(1);
  return false;
}

// One warm-up scenario, then one scenario per concurrency level (closed loop, VUs = level).
// Scenario tags put every metric of a level under `level:<n>`; warm-up is tagged `warmup`.
export function sweep(execName, extraMetrics = []) {
  const scenarios = {
    warmup: {
      executor: "constant-vus",
      vus: LEVELS[Math.min(2, LEVELS.length - 1)],
      duration: WARMUP,
      exec: execName,
      tags: { level: "warmup" },
    },
  };
  const thresholds = {};
  let start = seconds(WARMUP) + GAP;
  for (const level of LEVELS) {
    scenarios[`c${level}`] = {
      executor: "constant-vus",
      vus: level,
      duration: DURATION,
      startTime: `${start}s`,
      exec: execName,
      tags: { level: String(level) },
    };
    for (const m of ["http_req_duration", "http_reqs", "failed_non2xx", "failed_503", ...extraMetrics]) {
      thresholds[`${m}{level:${level}}`] = [m === "http_req_duration" ? "p(95)>=0" : "count>=0"];
    }
    start += seconds(DURATION) + GAP;
  }
  return { scenarios, thresholds, summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"] };
}

// One RESULT line per level; `rows` names the counter whose count is reported as rows_per_s.
export function summarize(data, label, rows) {
  const out = LEVELS.map((level) => {
    const v = (name) => data.metrics[`${name}{level:${level}}`]?.values || {};
    const d = v("http_req_duration");
    const secs = seconds(DURATION);
    const line =
      `RESULT ${label} c=${level} rps=${((v("http_reqs").count || 0) / secs).toFixed(1)} ` +
      (rows ? `rows_per_s=${((v(rows).count || 0) / secs).toFixed(0)} ` : "") +
      `p50=${d["p(50)"]?.toFixed(1)} p95=${d["p(95)"]?.toFixed(1)} p99=${d["p(99)"]?.toFixed(1)} ` +
      `non2xx=${v("failed_non2xx").count || 0} s503=${v("failed_503").count || 0}`;
    return line;
  });
  return { stdout: out.join("\n") + "\n" };
}
