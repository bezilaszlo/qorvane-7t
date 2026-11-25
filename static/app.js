const API = "/api/v1";
const DAY_MS = 86_400_000;
const PERIODS = [
  { key: "24h", label: "Today", days: 1, phrase: "the last 24 hours" },
  { key: "7d", label: "Last 7 days", days: 7, phrase: "the last 7 days" },
  { key: "30d", label: "Last 30 days", days: 30, phrase: "the last 30 days" },
];
const STATS = [
  { key: "avg", label: "Average" },
  { key: "min", label: "Lowest" },
  { key: "max", label: "Highest" },
  { key: "sum", label: "Total" },
];
const METRICS = {
  temperature: { label: "Temperature", unit: "°C", icon: "temperature", hi: "warmest", lo: "coolest" },
  humidity: { label: "Humidity", unit: "%", icon: "humidity", hi: "dampest", lo: "driest" },
  wind_speed: { label: "Wind", unit: "m/s", icon: "wind", hi: "windiest", lo: "calmest" },
};
const METRIC_ORDER = Object.keys(METRICS);
const TEMP_STOPS = [[0, 215], [0.4, 190], [0.5, 60], [0.7, 38], [1, 8]];
const tempHue = (t) => {
  for (let i = 1; i < TEMP_STOPS.length; i++) {
    const [t1, h1] = TEMP_STOPS[i];
    const [t0, h0] = TEMP_STOPS[i - 1];
    if (t <= t1) return h0 + ((h1 - h0) * (t - t0)) / (t1 - t0);
  }
  return TEMP_STOPS.at(-1)[1];
};
const PALETTE = ["#0e7490", "#d9480f", "#7c3aed", "#2f9e44", "#c2255c", "#a16207", "#1c7ed6", "#495057"];

const titleCase = (s) => s.replace(/[_-]+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase());
const pretty = (s) => titleCase(s).replace(/\s+/g, " ");
const meta = (m) => METRICS[m] || { label: titleCase(m), unit: "", icon: "generic", hi: "highest", lo: "lowest" };
const csv = (v) => (v ? v.split(",").filter(Boolean) : []);
const dayLabel = (d) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function errorLines(status, body) {
  if (status === 503) return ["The database is unavailable. Please try again in a moment."];
  const detail = body && body.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const field = (d.loc || []).filter((x) => x !== "query" && x !== "body").join(" / ");
      const msg = d.msg.charAt(0).toUpperCase() + d.msg.slice(1);
      return field ? `${titleCase(field)}: ${msg}` : msg;
    });
  }
  if (typeof detail === "string") return [detail.charAt(0).toUpperCase() + detail.slice(1)];
  return [`Something went wrong (HTTP ${status}).`];
}

class ApiError extends Error {
  constructor(lines) {
    super(lines.join("; "));
    this.lines = lines;
  }
}

async function getJson(url) {
  let res;
  try {
    res = await fetch(url);
  } catch {
    throw new ApiError(["Could not reach the server. Check your connection and try again."]);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorLines(res.status, body));
  return body;
}

let chartInst = null;

const toLocalInput = (d) => {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

document.addEventListener("alpine:init", () => {
  Alpine.data("app", () => ({
    periods: PERIODS,
    stats: STATS,
    sensors: [],
    metrics: [],
    selSensors: [],
    selMetrics: [],
    stat: "avg",
    period: "7d",
    start: "",
    end: "",
    chartMetric: "",
    loading: false,
    ready: false,
    errors: [],
    result: null,
    win: null,
    trend: null,
    hasChart: false,
    trendLoading: false,
    trendError: "",
    token: 0,
    test: { sensor_id: "", metric: "", value: "" },
    testMsg: "",
    testOk: true,
    pretty,
    meta,

    async init() {
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => this.drawChart());
      this.readUrl();
      await this.loadSensors();
      if (this.errors.length) return;
      await this.refresh();
    },

    readUrl() {
      const q = new URLSearchParams(location.search);
      if (q.get("period") && (PERIODS.some((p) => p.key === q.get("period")) || q.get("period") === "custom")) this.period = q.get("period");
      if (STATS.some((s) => s.key === q.get("stat"))) this.stat = q.get("stat");
      this.selSensors = csv(q.get("sensor"));
      this.selMetrics = csv(q.get("metric"));
      this.chartMetric = q.get("chart") || "";
      this.start = q.get("start") || "";
      this.end = q.get("end") || "";
      if (this.period === "custom" && !this.start) this.period = "7d";
    },

    writeUrl() {
      const q = new URLSearchParams({ period: this.period, stat: this.stat });
      if (this.selSensors.length) q.set("sensor", this.selSensors.join(","));
      q.set("metric", this.selMetrics.join(","));
      if (this.chartMetric) q.set("chart", this.chartMetric);
      if (this.period === "custom") {
        q.set("start", this.start);
        if (this.end) q.set("end", this.end);
      }
      try {
        history.replaceState(null, "", `?${q}`);
      } catch {}
    },

    async loadSensors() {
      try {
        const body = await getJson(`${API}/sensors`);
        const pairs = body.sensors;
        this.sensors = [...new Set(pairs.map((p) => p.sensor_id))].sort();
        const found = [...new Set(pairs.map((p) => p.metric))];
        this.metrics = [...METRIC_ORDER.filter((m) => found.includes(m)), ...found.filter((m) => !METRICS[m]).sort()];
      } catch (e) {
        this.errors = e.lines;
        return;
      }
      this.selSensors = this.selSensors.filter((s) => this.sensors.includes(s));
      this.selMetrics = this.selMetrics.filter((m) => this.metrics.includes(m));
      if (!this.selMetrics.length) this.selMetrics = [...this.metrics];
      if (!this.selMetrics.includes(this.chartMetric)) this.chartMetric = this.selMetrics[0] || "";
    },

    window() {
      if (this.period === "custom") {
        const s = new Date(this.start);
        const e = this.end ? new Date(this.end) : new Date();
        return { start: s, end: e };
      }
      const end = new Date();
      const days = PERIODS.find((p) => p.key === this.period).days;
      return { start: new Date(end.getTime() - days * DAY_MS), end };
    },

    setPeriod(key) {
      this.period = key;
      return this.refresh();
    },

    applyCustom() {
      if (!this.start) return;
      this.period = "custom";
      return this.refresh();
    },

    setStat(key) {
      this.stat = key;
      return this.refresh({ trend: false });
    },

    toggleSensor(s) {
      this.selSensors = this.selSensors.includes(s) ? this.selSensors.filter((x) => x !== s) : [...this.selSensors, s];
      if (this.selSensors.length === this.sensors.length) this.selSensors = [];
      return this.refresh();
    },

    clearSensors() {
      this.selSensors = [];
      return this.refresh();
    },

    toggleMetric(m) {
      if (this.selMetrics.includes(m)) {
        if (this.selMetrics.length === 1) return;
        this.selMetrics = this.selMetrics.filter((x) => x !== m);
      } else {
        this.selMetrics = this.metrics.filter((x) => x === m || this.selMetrics.includes(x));
      }
      if (!this.selMetrics.includes(this.chartMetric)) this.chartMetric = this.selMetrics[0];
      return this.refresh({ trend: false });
    },

    setChartMetric(m) {
      this.chartMetric = m;
      this.drawChart();
      this.writeUrl();
    },

    async refresh({ trend = true } = {}) {
      const token = ++this.token;
      this.errors = [];
      this.loading = true;
      this.writeUrl();
      const win = this.window();
      const q = new URLSearchParams({ stat: this.stat, start: win.start.toISOString(), end: win.end.toISOString() });
      this.selMetrics.forEach((m) => q.append("metric", m));
      this.selSensors.forEach((s) => q.append("sensor_id", s));
      try {
        const body = await getJson(`${API}/stats?${q}`);
        if (token !== this.token) return;
        this.result = body;
        this.win = win;
      } catch (e) {
        if (token !== this.token) return;
        this.errors = e.lines;
        this.result = null;
        this.trend = null;
        this.clearChart();
      } finally {
        if (token === this.token) {
          this.loading = false;
          this.ready = true;
        }
      }
      if (trend && this.result && this.period !== "24h") await this.loadTrend(token, win);
    },

    async loadTrend(token, win) {
      this.trendLoading = true;
      this.trendError = "";
      const n = clamp(Math.floor((win.end - win.start) / DAY_MS + 1e-6), 1, 31);
      const jobs = [];
      for (let i = 0; i < n; i++) {
        const s = new Date(win.start.getTime() + i * DAY_MS);
        const e = new Date(s.getTime() + DAY_MS);
        const q = new URLSearchParams({ stat: "avg", start: s.toISOString(), end: e.toISOString() });
        this.metrics.forEach((m) => q.append("metric", m));
        this.selSensors.forEach((x) => q.append("sensor_id", x));
        jobs.push(getJson(`${API}/stats?${q}`).then((b) => ({ s, e, rows: b.results })));
      }
      try {
        const days = await Promise.all(jobs);
        if (token !== this.token) return;
        this.trend = days;
        this.drawChart();
      } catch (e) {
        if (token !== this.token) return;
        this.trend = null;
        this.clearChart();
        this.trendError = `The day-by-day chart could not be loaded. ${e.lines.join(" ")}`;
      } finally {
        if (token === this.token) this.trendLoading = false;
      }
    },

    color(sensor) {
      return PALETTE[Math.max(0, this.sensors.indexOf(sensor)) % PALETTE.length];
    },

    fmt(v) {
      if (!Number.isFinite(v)) return String(v);
      const a = Math.abs(v);
      // One decimal everywhere so values line up (no "4" next to "7.08"); integers past 1000.
      const digits = a >= 1000 ? 0 : 1;
      return v
        .toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
        .replace("-", "−");
    },

    periodPhrase() {
      if (this.period !== "custom") return PERIODS.find((p) => p.key === this.period).phrase;
      return `${dayLabel(this.win.start)} to ${dayLabel(this.win.end)}`;
    },

    windowText() {
      if (!this.win) return "";
      const f = (d) => d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      return `${STATS.find((s) => s.key === this.stat).label} from ${f(this.win.start)} to ${f(this.win.end)}.`;
    },

    statPhrase() {
      const label = STATS.find((s) => s.key === this.stat).label;
      return { title: this.stat === "sum" ? "Total per station" : `${label} per station` };
    },

    insight() {
      if (!this.result || !this.result.results.length) return "";
      const m = this.selMetrics.find((x) => this.result.results.some((r) => r.metric === x)) || this.result.results[0].metric;
      const mm = meta(m);
      const rows = this.result.results.filter((r) => r.metric === m).sort((a, b) => b.value - a.value);
      const val = (r) => `${this.fmt(r.value)}${mm.unit ? "\u00a0" + mm.unit : ""}`;
      const name = (r) => `the ${pretty(r.sensor_id)}`;
      const when = this.period === "custom" ? `Between ${this.periodPhrase()}` : `Over ${this.periodPhrase()}`;
      const lower = mm.label.toLowerCase();
      const first = rows[0];
      const last = rows[rows.length - 1];
      if (rows.length === 1) {
        const verb = { avg: "averaged", min: "dropped to a low of", max: "peaked at", sum: "added up to" }[this.stat];
        return `${when}, ${lower} at ${pretty(first.sensor_id)} ${verb} ${val(first)}.`;
      }
      if (this.stat === "sum") {
        return `${when}, ${name(first)} had the highest total ${lower} (${val(first)}) and ${name(last)} the lowest (${val(last)}).`;
      }
      if (this.stat === "min") {
        return `${when}, ${lower} dropped lowest at ${name(last)} (${val(last)}); ${name(first)} never fell below ${val(first)}.`;
      }
      if (this.stat === "max") {
        return `${when}, ${lower} peaked highest at ${name(first)} (${val(first)}); ${name(last)} never rose above ${val(last)}.`;
      }
      return `${when}, ${name(first)} was the ${mm.hi} spot (average ${val(first)}) and ${name(last)} the ${mm.lo} (${val(last)}).`;
    },

    cards() {
      if (!this.result) return [];
      const by = {};
      for (const r of this.result.results) (by[r.sensor_id] ||= {})[r.metric] = r;
      const maxOf = {};
      for (const r of this.result.results) maxOf[r.metric] = Math.max(maxOf[r.metric] || 0, Math.abs(r.value));
      return Object.keys(by)
        .sort()
        .map((sensor) => ({
          sensor,
          rows: this.selMetrics
            .filter((m) => by[sensor][m])
            .map((m) => this.cardRow(by[sensor][m], maxOf[m])),
        }));
    },

    cardRow(r, max) {
      const row = { ...r, kind: "", pct: 0, tint: "" };
      const total = this.stat === "sum";
      if (r.metric === "temperature" && !total) {
        const t = clamp((r.value + 10) / 45, 0, 1);
        row.kind = "temp";
        row.pct = t * 100;
        row.tint = `hsl(${Math.round(tempHue(t))} 78% var(--tint-l))`;
      } else if (r.metric === "humidity" && !total) {
        row.kind = "humid";
        row.pct = clamp(r.value, 0, 100);
      } else if (r.metric === "wind_speed") {
        row.kind = "wind";
        row.pct = max ? (Math.abs(r.value) / max) * 100 : 0;
      }
      return row;
    },

    groups() {
      if (!this.result) return [];
      const by = {};
      for (const r of this.result.results) (by[r.metric] ||= []).push(r);
      return this.selMetrics
        .filter((m) => by[m])
        .map((metric) => {
          const rows = by[metric].sort((a, b) => b.value - a.value);
          const lo = Math.min(0, ...rows.map((r) => r.value));
          const hi = Math.max(0, ...rows.map((r) => r.value));
          const span = hi - lo || 1;
          return {
            metric,
            zero: (-lo / span) * 100,
            rows: rows.map((r) => ({
              ...r,
              left: ((Math.min(0, r.value) - lo) / span) * 100,
              width: Math.max((Math.abs(r.value) / span) * 100, 1.5),
            })),
          };
        });
    },

    sortedResults() {
      if (!this.result) return [];
      const order = (m) => this.metrics.indexOf(m);
      return [...this.result.results].sort((a, b) => a.sensor_id.localeCompare(b.sensor_id) || order(a.metric) - order(b.metric));
    },

    clearChart() {
      if (chartInst) chartInst.destroy();
      chartInst = null;
      this.hasChart = false;
    },

    async drawChart() {
      this.hasChart = !!this.trend && this.trend.some((d) => d.rows.some((r) => r.metric === this.chartMetric));
      await this.$nextTick();
      if (chartInst) chartInst.destroy();
      chartInst = null;
      const m = this.chartMetric;
      const canvas = this.$refs.canvas;
      if (!this.hasChart || !canvas) return;
      const days = this.trend;
      const ids = [...new Set(days.flatMap((d) => d.rows.filter((r) => r.metric === m).map((r) => r.sensor_id)))].sort();
      const unit = meta(m).unit;
      const css = getComputedStyle(document.documentElement);
      const ink = css.getPropertyValue("--muted").trim();
      const grid = css.getPropertyValue("--line").trim();
      const card = css.getPropertyValue("--card").trim();
      const last = days.length - 1;
      const labels = days.map((d, i) => (this.period !== "custom" && i === last ? "Today" : dayLabel(new Date(d.e.getTime() - 1))));
      const longDates = days.map((d) => new Date(d.e.getTime() - 1).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }));
      const datasets = ids.map((sensor) => ({
        label: pretty(sensor),
        data: days.map((d) => d.rows.find((r) => r.metric === m && r.sensor_id === sensor)?.value ?? null),
        borderColor: this.color(sensor),
        backgroundColor: this.color(sensor),
        borderWidth: 2.4,
        pointRadius: days.length <= 8 ? 3 : 2,
        pointHoverRadius: 5,
        tension: 0,
        spanGaps: false,
      }));
      chartInst = new Chart(canvas, {
        type: "line",
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: { mode: "index", intersect: false },
          scales: {
            x: { grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkipPadding: 14 }, border: { color: grid } },
            y: {
              grid: { color: grid },
              border: { display: false },
              ticks: { color: ink, callback: (v) => this.fmt(v) },
              title: { display: !!unit, text: unit, color: ink },
            },
          },
          plugins: {
            legend: { position: "bottom", labels: { color: ink, usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
            tooltip: {
              backgroundColor: card,
              titleColor: css.getPropertyValue("--ink").trim(),
              bodyColor: css.getPropertyValue("--ink").trim(),
              borderColor: grid,
              borderWidth: 1,
              usePointStyle: true,
              callbacks: {
                title: (items) => longDates[items[0].dataIndex],
                label: (c) => `${c.dataset.label}: ${this.fmt(c.parsed.y)}${unit ? " " + unit : ""}`,
              },
            },
          },
        },
      });
    },

    async sendTest() {
      const value = Number(this.test.value);
      if (this.test.value.trim() === "" || !Number.isFinite(value)) {
        this.testOk = false;
        this.testMsg = "The value must be a number.";
        return;
      }
      try {
        const res = await fetch(`${API}/readings`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ readings: [{ sensor_id: this.test.sensor_id, metrics: { [this.test.metric]: value } }] }),
        });
        const body = await res.json().catch(() => null);
        this.testOk = res.ok;
        this.testMsg = res.ok
          ? body.inserted ? "Reading saved." : "That reading was already saved."
          : errorLines(res.status, body).join(" ");
        if (res.ok) {
          await this.loadSensors();
          await this.refresh();
        }
      } catch {
        this.testOk = false;
        this.testMsg = "Could not reach the server.";
      }
    },
  }));
});
