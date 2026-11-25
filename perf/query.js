import http from "k6/http";
import { BASE_URL, record, sweep, summarize } from "./lib.js";

const CASE = __ENV.CASE || "day_single";
const SENSORS = parseInt(__ENV.SENSORS || "10");
const STAT = __ENV.STAT || "avg";

const CASES = {
  day_single: { days: 1, single: true },
  day_all: { days: 1, single: false },
  d30_single: { days: 30, single: true },
  d30_all: { days: 30, single: false },
};
const c = CASES[CASE];

export const options = sweep("query");

export function query() {
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
  record(http.get(`${BASE_URL}/api/v1/stats?${params.join("&")}`));
}

export function handleSummary(data) {
  return summarize(data, CASE);
}
