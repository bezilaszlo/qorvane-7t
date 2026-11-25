const API = "/api/v1";
const DAY_MS = 86_400_000;
const PRESETS = { "24h": 1, "7d": 7, "30d": 30 };

function errorLines(status, body) {
  if (status === 503) return ["Database unavailable. Try again shortly."];
  const detail = body && body.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).join(".")}: ${d.msg}`);
  }
  if (typeof detail === "string") return [detail];
  return [`Request failed (HTTP ${status}).`];
}

const toIso = (local) => (local ? new Date(local).toISOString() : null);

function toLocalInput(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`;
}

document.addEventListener("alpine:init", () => {
  Alpine.data("app", () => ({
    pairs: [],
    sensors: [],
    metrics: [],
    selSensors: [],
    selMetrics: [],
    stat: "avg",
    start: "",
    end: "",
    preset: "24h",
    loading: false,
    errors: [],
    result: null,
    test: { sensor_id: "", metric: "", value: "" },
    testMsg: "",
    testOk: true,

    async init() {
      await this.loadSensors();
      if (this.selMetrics.length) await this.run();
    },

    async loadSensors() {
      try {
        const res = await fetch(`${API}/sensors`);
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          this.errors = errorLines(res.status, body);
          return;
        }
        this.pairs = body.sensors;
      } catch {
        this.errors = ["Network error loading sensors."];
        return;
      }
      this.sensors = [...new Set(this.pairs.map((p) => p.sensor_id))];
      this.metrics = [...new Set(this.pairs.map((p) => p.metric))].sort();
      this.selSensors = this.selSensors.filter((s) => this.sensors.includes(s));
      this.selMetrics = this.selMetrics.filter((m) => this.metrics.includes(m));
      if (!this.selMetrics.length) this.selMetrics = [...this.metrics];
    },

    setPreset(key) {
      this.preset = key;
      this.start = toLocalInput(new Date(Date.now() - PRESETS[key] * DAY_MS));
      this.end = "";
    },

    clearPreset() {
      this.preset = "";
    },

    async run() {
      this.errors = [];
      if (!this.selMetrics.length) {
        this.errors = ["Select at least one metric."];
        return;
      }
      const q = new URLSearchParams({ stat: this.stat });
      this.selMetrics.forEach((m) => q.append("metric", m));
      this.selSensors.forEach((s) => q.append("sensor_id", s));
      // a preset sends an exact start (second precision); end defaults to server now
      const start = this.preset
        ? new Date(Date.now() - PRESETS[this.preset] * DAY_MS).toISOString()
        : toIso(this.start);
      const end = this.preset ? null : toIso(this.end);
      if (start) q.set("start", start);
      if (end) q.set("end", end);

      this.loading = true;
      try {
        const res = await fetch(`${API}/stats?${q}`);
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          this.errors = errorLines(res.status, body);
          this.result = null;
        } else {
          this.result = body;
        }
      } catch {
        this.errors = ["Network error: could not reach the API."];
        this.result = null;
      } finally {
        this.loading = false;
      }
    },

    fmt(v) {
      if (!Number.isFinite(v)) return String(v);
      const a = Math.abs(v);
      return v.toLocaleString(undefined, {
        maximumFractionDigits: a >= 1000 ? 0 : a >= 10 ? 1 : 2,
      });
    },

    fmtTs(iso) {
      return new Date(iso).toLocaleString();
    },

    groups() {
      if (!this.result) return [];
      const by = {};
      for (const r of this.result.results) (by[r.metric] ||= []).push(r);
      return Object.entries(by)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([metric, rows]) => {
          const max = Math.max(...rows.map((r) => Math.abs(r.value))) || 1;
          rows.sort((a, b) => a.sensor_id.localeCompare(b.sensor_id));
          return { metric, rows: rows.map((r) => ({ ...r, pct: (Math.abs(r.value) / max) * 100 })) };
        });
    },

    sortedResults() {
      if (!this.result) return [];
      return [...this.result.results].sort(
        (a, b) => a.sensor_id.localeCompare(b.sensor_id) || a.metric.localeCompare(b.metric),
      );
    },

    async sendTest() {
      const value = Number(this.test.value);
      if (this.test.value.trim() === "" || !Number.isFinite(value)) {
        this.testOk = false;
        this.testMsg = "Value must be a number.";
        return;
      }
      try {
        const res = await fetch(`${API}/readings`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            readings: [{ sensor_id: this.test.sensor_id, metrics: { [this.test.metric]: value } }],
          }),
        });
        const body = await res.json().catch(() => null);
        this.testOk = res.ok;
        this.testMsg = res.ok
          ? `inserted ${body.inserted}, duplicates ${body.duplicates}`
          : errorLines(res.status, body).join("; ");
        if (res.ok) {
          await this.loadSensors();
          await this.run();
        }
      } catch {
        this.testOk = false;
        this.testMsg = "Network error.";
      }
    },
  }));
});
