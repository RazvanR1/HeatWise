/* HeatWise sidebar panel for Home Assistant. Plain web component, no build step. */

const STR = {
  en: {
    title: "HeatWise",
    controlling: "In control",
    observing: "Observing only",
    observing_hint: "HeatWise shows what it would do and sends no commands.",
    take_control: "Let HeatWise control",
    confirm_control: "Tap again: HeatWise will drive the boiler, valves and ACs",
    stop_control: "Observe only",
    source: "Heat source",
    boiler: "Boiler",
    ac: "Air conditioner",
    home: "Someone home",
    nobody: "Nobody home",
    target: "Target",
    now: "Now",
    outdoor: "Outdoor",
    boiler_target: "Main thermostat",
    burner_today: "Burner today",
    burning: "burning now",
    cop: "AC efficiency (COP)",
    cost: "Cost of 1 kWh of heat",
    gas: "gas",
    use_ac: "Heat with ACs",
    on: "On",
    off: "Off",
    heating: "Heating",
    idle: "Idle",
    stopped: "Off",
    manual_until: "Manual until",
    zones: "Rooms",
    chart: "Last 24 hours",
    room_temp: "House temperature",
    target_line: "HeatWise target",
    burner_on: "Burner on",
    no_house: "No HeatWise house yet. Add it from Settings → Devices & services → Add integration → HeatWise.",
    loading: "Loading…",
    no_history: "History appears after HeatWise has run for a while.",
    valve: "Valve",
    presets: { schedule: "Schedule", comfort: "Comfort", eco: "Eco", away: "Away", boost: "Boost" },
  },
  ro: {
    title: "HeatWise",
    controlling: "Controlează",
    observing: "Doar observă",
    observing_hint: "HeatWise arată ce ar face și nu trimite nicio comandă.",
    take_control: "Lasă HeatWise să controleze",
    confirm_control: "Apasă din nou: HeatWise va comanda centrala, capetele și AC-urile",
    stop_control: "Doar observă",
    source: "Sursa de căldură",
    boiler: "Centrala",
    ac: "Aer condiționat",
    home: "E cineva acasă",
    nobody: "Nu e nimeni acasă",
    target: "Țintă",
    now: "Acum",
    outdoor: "Afară",
    boiler_target: "Termostatul principal",
    burner_today: "Arzător azi",
    burning: "arde acum",
    cop: "Eficiența AC (COP)",
    cost: "Cost 1 kWh căldură",
    gas: "gaz",
    use_ac: "Încălzire cu AC",
    on: "Pornit",
    off: "Oprit",
    heating: "Încălzește",
    idle: "În așteptare",
    stopped: "Oprit",
    manual_until: "Manual până la",
    zones: "Camere",
    chart: "Ultimele 24 de ore",
    room_temp: "Temperatura casei",
    target_line: "Ținta HeatWise",
    burner_on: "Arzător pornit",
    no_house: "Nu există încă o casă HeatWise. Adaug-o din Setări → Dispozitive și servicii → Adaugă integrare → HeatWise.",
    loading: "Se încarcă…",
    no_history: "Istoricul apare după ce HeatWise rulează o vreme.",
    valve: "Cap termostatic",
    presets: { schedule: "Program", comfort: "Confort", eco: "Eco", away: "Plecat", boost: "Boost" },
  },
};

const ICONS = { house: "mdi:home-thermometer", ac: "mdi:air-conditioner", trv: "mdi:radiator", mixed: "mdi:radiator" };
const PRESETS = ["schedule", "comfort", "eco", "away", "boost"];

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

const fmtT = (v, digits = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(digits)}°`);

class HeatWisePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._houses = null;
    this._idx = 0;
    this._history = null;
    this._confirm = null;
    this._pending = {};
    this._sig = "";
    this._raf = null;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
    this._schedule();
  }

  set narrow(v) {
    this._narrow = v;
    this._schedule(true);
  }

  set panel(_p) {}

  connectedCallback() {
    this._timer = setInterval(() => this._load(), 60000);
    this._htimer = setInterval(() => this._loadHistory(), 300000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    clearInterval(this._htimer);
  }

  get _t() {
    const lang = (this._hass?.language || "en").slice(0, 2);
    return STR[lang] || STR.en;
  }

  get _house() {
    return this._houses?.[this._idx] || null;
  }

  _st(id) {
    return id ? this._hass?.states?.[id] : undefined;
  }

  async _load() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({ type: "heatwise/status" });
      this._houses = res.houses || [];
      if (this._idx >= this._houses.length) this._idx = 0;
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._schedule(true);
    if (!this._history) this._loadHistory();
  }

  async _loadHistory() {
    const h = this._house;
    if (!h || !this._hass) return;
    const house = h.zones.find((z) => z.kind === "house");
    const ids = [house?.climate, h.entities.boiler_target, h.outdoor, h.entities.burner_running].filter(Boolean);
    try {
      const start = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start,
        entity_ids: ids,
        minimal_response: false,
        no_attributes: false,
        significant_changes_only: false,
      });
      this._history = { res, ids: { house: house?.climate, target: h.entities.boiler_target, outdoor: h.outdoor, burner: h.entities.burner_running } };
    } catch (_e) {
      this._history = { res: {}, ids: {} };
    }
    this._schedule(true);
  }

  _schedule(force = false) {
    if (force) this._sig = "";
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._render();
    });
  }

  _signature() {
    const h = this._house;
    if (!h) return `none-${this._error}-${!!this._houses}`;
    const ids = [...h.zones.map((z) => z.climate), ...Object.values(h.entities), h.outdoor];
    return ids.map((id) => this._st(id)?.last_updated || "").join("|") + `|${this._confirm}|${this._narrow}|${this._idx}`;
  }

  /* ------------------------------------------------------------ actions */
  _call(domain, service, data) {
    return this._hass.callService(domain, service, data);
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const { act, entity, value } = el.dataset;
    if (act === "preset") this._call("climate", "set_preset_mode", { entity_id: entity, preset_mode: value });
    else if (act === "temp") this._nudge(entity, parseFloat(value));
    else if (act === "power") this._call("climate", "set_hvac_mode", { entity_id: entity, hvac_mode: value });
    else if (act === "house") {
      this._idx = parseInt(value, 10);
      this._history = null;
      this._loadHistory();
      this._schedule(true);
    } else if (act === "control") this._toggleControl(entity, value === "on");
    else if (act === "use_ac") this._call("switch", value === "on" ? "turn_on" : "turn_off", { entity_id: entity });
  }

  _toggleControl(entity, turnOn) {
    if (!turnOn) {
      this._call("switch", "turn_off", { entity_id: entity });
      return;
    }
    if (this._confirm !== "control") {
      this._confirm = "control";
      clearTimeout(this._confirmTimer);
      this._confirmTimer = setTimeout(() => {
        this._confirm = null;
        this._schedule(true);
      }, 5000);
      this._schedule(true);
      return;
    }
    this._confirm = null;
    this._call("switch", "turn_on", { entity_id: entity });
    this._schedule(true);
  }

  _nudge(entity, delta) {
    const st = this._st(entity);
    const base = this._pending[entity]?.value ?? num(st?.attributes?.temperature) ?? 20;
    const value = Math.min(30, Math.max(5, Math.round((base + delta) * 2) / 2));
    clearTimeout(this._pending[entity]?.timer);
    const timer = setTimeout(() => {
      delete this._pending[entity];
      this._call("climate", "set_temperature", { entity_id: entity, temperature: value });
    }, 700);
    this._pending[entity] = { value, timer };
    this._schedule(true);
  }

  /* ------------------------------------------------------------- render */
  _render() {
    if (!this._hass) return;
    const sig = this._signature();
    if (sig === this._sig) return;
    this._sig = sig;
    const t = this._t;
    let body;
    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!this._houses) body = `<div class="empty">${t.loading}</div>`;
    else if (!this._houses.length) body = `<div class="empty">${esc(t.no_house)}</div>`;
    else body = this._renderHouse(this._house);

    this.shadowRoot.innerHTML = `<style>${CSS}</style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="title"><ha-icon icon="mdi:radiator"></ha-icon>${t.title}</div>
        ${this._houses && this._houses.length > 1 ? `<div class="tabs">${this._houses
          .map((h, i) => `<button class="tab ${i === this._idx ? "active" : ""}" data-act="house" data-value="${i}">${esc(h.name)}</button>`)
          .join("")}</div>` : ""}
      </div>
      <div class="content">${body}</div>`;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) {
      menu.hass = this._hass;
      menu.narrow = this._narrow;
    }
  }

  _renderHouse(h) {
    const t = this._t;
    const e = h.entities;
    const control = this._st(e.control);
    const controlling = control?.state === "on";
    const decision = this._st(e.decision);
    const source = this._st(e.heat_source);
    const home = this._st(e.anyone_home);
    const house = h.zones.find((z) => z.kind === "house");
    const rooms = h.zones.filter((z) => z.kind !== "house");

    const statusPill = controlling
      ? `<span class="pill ok"><ha-icon icon="mdi:robot"></ha-icon>${t.controlling}</span>`
      : `<span class="pill warn"><ha-icon icon="mdi:eye-outline"></ha-icon>${t.observing}</span>`;
    const controlBtn = e.control
      ? controlling
        ? `<button class="btn ghost" data-act="control" data-entity="${e.control}" data-value="off">${t.stop_control}</button>`
        : `<button class="btn ${this._confirm === "control" ? "danger" : "primary"}" data-act="control" data-entity="${e.control}" data-value="on">${this._confirm === "control" ? t.confirm_control : t.take_control}</button>`
      : "";

    const pills = [statusPill];
    if (source) {
      const isAc = source.state === "ac";
      pills.push(`<span class="pill ${isAc ? "ac" : "heat"}"><ha-icon icon="${isAc ? "mdi:air-conditioner" : "mdi:fire"}"></ha-icon>${isAc ? t.ac : t.boiler}</span>`);
    }
    if (home && home.state !== "unavailable") {
      pills.push(`<span class="pill"><ha-icon icon="${home.state === "on" ? "mdi:home-account" : "mdi:home-outline"}"></ha-icon>${home.state === "on" ? t.home : t.nobody}</span>`);
    }

    return `
      <div class="status">
        <div class="pills">${pills.join("")}</div>
        <div class="status-actions">
          ${e.use_ac ? this._switch(e.use_ac, t.use_ac, "use_ac") : ""}
          ${controlBtn}
        </div>
      </div>
      ${!controlling ? `<div class="hint">${t.observing_hint}</div>` : ""}
      ${house ? this._renderHero(house, decision) : ""}
      ${this._renderStats(h, source)}
      ${rooms.length ? `<h2>${t.zones}</h2><div class="grid">${rooms.map((z) => this._renderZone(z)).join("")}</div>` : ""}
      <h2>${t.chart}</h2>
      <div class="card chart-card">${this._renderChart()}</div>`;
  }

  _switch(entity, label, act) {
    const st = this._st(entity);
    const on = st?.state === "on";
    return `<button class="toggle ${on ? "on" : ""}" data-act="${act}" data-entity="${entity}" data-value="${on ? "off" : "on"}">
      <span class="knob"></span>${esc(label)}</button>`;
  }

  _targetOf(zone) {
    const st = this._st(zone.climate);
    return this._pending[zone.climate]?.value ?? num(st?.attributes?.temperature);
  }

  _presetRow(zone) {
    const st = this._st(zone.climate);
    const cur = st?.attributes?.preset_mode;
    return `<div class="presets">${PRESETS.map(
      (p) => `<button class="chip ${cur === p ? "active" : ""}" data-act="preset" data-entity="${zone.climate}" data-value="${p}">${this._t.presets[p]}</button>`
    ).join("")}</div>`;
  }

  _actionBadge(st) {
    const t = this._t;
    if (!st || st.state === "off") return `<span class="badge off">${t.stopped}</span>`;
    if (st.attributes.hvac_action === "heating") return `<span class="badge heating"><ha-icon icon="mdi:fire"></ha-icon>${t.heating}</span>`;
    return `<span class="badge">${t.idle}</span>`;
  }

  _manual(st) {
    const until = st?.attributes?.manual_until;
    if (!until) return "";
    const d = new Date(until);
    const time = d.toLocaleTimeString(this._hass.language || undefined, { hour: "2-digit", minute: "2-digit" });
    return `<div class="manual"><ha-icon icon="mdi:hand-back-right-outline"></ha-icon>${this._t.manual_until} ${time}</div>`;
  }

  _tempControl(zone, big = false) {
    const target = this._targetOf(zone);
    return `<div class="tempctl ${big ? "big" : ""}">
      <button class="round" data-act="temp" data-entity="${zone.climate}" data-value="-0.5" aria-label="-">−</button>
      <div class="target"><span class="label">${this._t.target}</span><span class="val">${fmtT(target)}</span></div>
      <button class="round" data-act="temp" data-entity="${zone.climate}" data-value="0.5" aria-label="+">+</button>
    </div>`;
  }

  _powerBtn(zone, st) {
    const on = st && st.state !== "off";
    return `<button class="icon-btn ${on ? "on" : ""}" data-act="power" data-entity="${zone.climate}" data-value="${on ? "off" : "heat"}" title="${on ? this._t.on : this._t.off}">
      <ha-icon icon="mdi:power"></ha-icon></button>`;
  }

  _renderHero(zone, decision) {
    const st = this._st(zone.climate);
    const cur = num(st?.attributes?.current_temperature);
    const text = decision?.state && decision.state !== "unknown" ? decision.state : st?.attributes?.explanation || "";
    return `<div class="card hero">
      <div class="hero-main">
        <div class="hero-head"><ha-icon icon="${ICONS.house}"></ha-icon><span>${esc(zone.name)}</span>${this._actionBadge(st)}${this._powerBtn(zone, st)}</div>
        <div class="hero-temp">${fmtT(cur)}</div>
        <div class="decision"><ha-icon icon="mdi:head-lightbulb-outline"></ha-icon><span>${esc(text)}</span></div>
        ${this._manual(st)}
      </div>
      <div class="hero-side">
        ${this._tempControl(zone, true)}
        ${this._presetRow(zone)}
      </div>
    </div>`;
  }

  _renderStats(h, source) {
    const t = this._t;
    const tiles = [];
    const out = this._st(h.outdoor);
    if (out) {
      const v = h.outdoor.startsWith("weather.") ? num(out.attributes.temperature) : num(out.state);
      tiles.push(this._tile("mdi:thermometer", t.outdoor, fmtT(v)));
    }
    const bt = this._st(h.entities.boiler_target);
    if (bt) tiles.push(this._tile("mdi:thermostat", t.boiler_target, fmtT(num(bt.state))));
    const rt = this._st(h.entities.burner_runtime);
    if (rt) {
      const hours = num(rt.state) || 0;
      const hh = Math.floor(hours);
      const mm = Math.round((hours - hh) * 60);
      const burning = this._st(h.entities.burner_running)?.state === "on";
      tiles.push(this._tile("mdi:fire", t.burner_today, `${hh} h ${String(mm).padStart(2, "0")} min`, burning ? `<span class="live"></span>${t.burning}` : ""));
    }
    if (source) {
      const a = source.attributes;
      if (a.estimated_cop) tiles.push(this._tile("mdi:air-conditioner", t.cop, Number(a.estimated_cop).toFixed(1)));
      if (a.gas_cost_per_kwh_heat && a.ac_cost_per_kwh_heat) {
        tiles.push(this._tile("mdi:cash", t.cost, `${Number(a.ac_cost_per_kwh_heat).toFixed(2)} AC`, `${Number(a.gas_cost_per_kwh_heat).toFixed(2)} ${t.gas}`));
      }
    }
    return tiles.length ? `<div class="stats">${tiles.join("")}</div>` : "";
  }

  _tile(icon, label, value, sub = "") {
    return `<div class="card tile"><ha-icon icon="${icon}"></ha-icon><div><div class="tile-label">${esc(label)}</div><div class="tile-val">${esc(value)}</div>${sub ? `<div class="tile-sub">${sub}</div>` : ""}</div></div>`;
  }

  _renderZone(zone) {
    const st = this._st(zone.climate);
    const a = st?.attributes || {};
    const cur = num(a.current_temperature);
    const target = this._targetOf(zone);
    const behind = cur !== null && target !== null && cur < target - 0.3;
    return `<div class="card zone ${behind ? "cold" : ""}">
      <div class="zone-head">
        <ha-icon icon="${ICONS[zone.kind] || ICONS.trv}"></ha-icon>
        <span class="zone-name">${esc(zone.name)}</span>
        ${this._actionBadge(st)}
        ${this._powerBtn(zone, st)}
      </div>
      <div class="zone-temps"><span class="zone-now">${fmtT(cur)}</span></div>
      <div class="zone-why">${esc(a.explanation || "")}</div>
      ${this._manual(st)}
      ${this._tempControl(zone)}
      ${this._presetRow(zone)}
    </div>`;
  }

  /* -------------------------------------------------------------- chart */
  _series(entityId, pick) {
    const rows = this._history?.res?.[entityId] || [];
    const pts = [];
    for (const r of rows) {
      const v = pick(r);
      const ts = (r.lu ?? r.lc) * 1000;
      if (Number.isFinite(ts)) pts.push([ts, v]);
    }
    return pts;
  }

  _renderChart() {
    const t = this._t;
    if (!this._history) return `<div class="empty small">${t.loading}</div>`;
    const ids = this._history.ids;
    const room = this._series(ids.house, (r) => num(r.a?.current_temperature)).filter((p) => p[1] !== null);
    const target = this._series(ids.target, (r) => num(r.s)).filter((p) => p[1] !== null);
    const outdoor = ids.outdoor
      ? this._series(ids.outdoor, (r) => (ids.outdoor.startsWith("weather.") ? num(r.a?.temperature) : num(r.s))).filter((p) => p[1] !== null)
      : [];
    const burner = ids.burner ? this._series(ids.burner, (r) => r.s === "on") : [];
    if (room.length < 2 && target.length < 2) return `<div class="empty small">${t.no_history}</div>`;

    const now = Date.now();
    const x0 = now - 24 * 3600 * 1000;
    const vals = [...room, ...target, ...outdoor].map((p) => p[1]);
    let lo = Math.floor(Math.min(...vals) - 1);
    let hi = Math.ceil(Math.max(...vals) + 1);
    if (hi - lo < 4) hi = lo + 4;
    const W = 1000;
    const H = 240;
    const X = (ts) => ((Math.max(ts, x0) - x0) / (now - x0)) * W;
    const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
    const step = (pts) => {
      if (!pts.length) return "";
      let d = `M${X(pts[0][0]).toFixed(1)},${Y(pts[0][1]).toFixed(1)}`;
      for (let i = 1; i < pts.length; i++) d += ` H${X(pts[i][0]).toFixed(1)} V${Y(pts[i][1]).toFixed(1)}`;
      return d + ` H${W}`;
    };
    const line = (pts) => {
      if (!pts.length) return "";
      return pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ") + ` L${W},${Y(pts[pts.length - 1][1]).toFixed(1)}`;
    };
    let bands = "";
    for (let i = 0; i < burner.length; i++) {
      if (!burner[i][1]) continue;
      const end = i + 1 < burner.length ? burner[i + 1][0] : now;
      const a = X(burner[i][0]);
      const b = X(end);
      if (b > a) bands += `<rect x="${a.toFixed(1)}" y="0" width="${(b - a).toFixed(1)}" height="${H}" class="band"/>`;
    }
    const grid = [];
    const yl = [];
    const stepY = hi - lo > 10 ? 4 : 2;
    for (let v = Math.ceil(lo / stepY) * stepY; v <= hi; v += stepY) {
      grid.push(`<line x1="0" x2="${W}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="grid"/>`);
      yl.push(`<span class="ylab" style="top:${((Y(v) / H) * 100).toFixed(2)}%">${v}°</span>`);
    }
    const xl = [];
    for (let k = 0; k <= 4; k += this._narrow ? 2 : 1) {
      const ts = x0 + (k * (now - x0)) / 4;
      const label = new Date(ts).toLocaleTimeString(this._hass.language || undefined, { hour: "2-digit", minute: "2-digit" });
      xl.push(`<span class="xlab" style="left:${k * 25}%">${label}</span>`);
    }
    const legend = [
      `<span class="lg"><i class="sw room"></i>${t.room_temp}</span>`,
      `<span class="lg"><i class="sw target"></i>${t.target_line}</span>`,
      outdoor.length ? `<span class="lg"><i class="sw outdoor"></i>${t.outdoor}</span>` : "",
      burner.length ? `<span class="lg"><i class="sw band"></i>${t.burner_on}</span>` : "",
    ].join("");
    return `<div class="legend">${legend}</div>
      <div class="chart">
        <div class="ylabels">${yl.join("")}</div>
        <div class="plot">
          <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
            ${bands}${grid.join("")}
            <path d="${line(outdoor)}" class="outdoor"/>
            <path d="${step(target)}" class="target"/>
            <path d="${line(room)}" class="room"/>
          </svg>
          <div class="xlabels">${xl.join("")}</div>
        </div>
      </div>`;
  }
}

const CSS = `
  :host { display:block; min-height:100%; background:var(--primary-background-color); color:var(--primary-text-color);
    --hw-heat: var(--state-climate-heat-color, #ff8a3d); --hw-ac: var(--state-climate-cool-color, #3b9fe8);
    --hw-ok: var(--success-color, #43a047); --hw-warn: var(--warning-color, #f5a623);
    --hw-radius: var(--ha-card-border-radius, 16px); font-family: var(--paper-font-body1_-_font-family, inherit); }
  * { box-sizing:border-box; }
  .toolbar { display:flex; align-items:center; gap:8px; height:var(--header-height, 56px); padding:0 12px;
    background:var(--app-header-background-color, var(--primary-background-color)); color:var(--app-header-text-color, var(--primary-text-color));
    border-bottom:1px solid var(--divider-color); position:sticky; top:0; z-index:2; }
  .title { display:flex; align-items:center; gap:8px; font-size:20px; font-weight:500; }
  .title ha-icon { color:var(--hw-heat); }
  .tabs { margin-left:auto; display:flex; gap:6px; }
  .tab { border:1px solid var(--divider-color); background:none; color:inherit; padding:6px 12px; border-radius:999px; cursor:pointer; font:inherit; }
  .tab.active { background:var(--primary-color); border-color:var(--primary-color); color:var(--text-primary-color, #fff); }
  .content { max-width:1200px; margin:0 auto; padding:16px; }
  h2 { font-size:15px; font-weight:500; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:.06em; margin:24px 4px 10px; }
  .card { background:var(--ha-card-background, var(--card-background-color)); border-radius:var(--hw-radius);
    border:1px solid var(--ha-card-border-color, var(--divider-color)); box-shadow:var(--ha-card-box-shadow, none); padding:16px; }
  .empty { padding:48px 16px; text-align:center; color:var(--secondary-text-color); }
  .empty.small { padding:32px 8px; }
  .status { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .pills { display:flex; flex-wrap:wrap; gap:8px; }
  .pill { display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:999px; font-size:14px;
    background:var(--secondary-background-color); color:var(--primary-text-color); }
  .pill ha-icon { --mdc-icon-size:18px; }
  .pill.ok { background:color-mix(in srgb, var(--hw-ok) 18%, transparent); color:var(--hw-ok); }
  .pill.warn { background:color-mix(in srgb, var(--hw-warn) 18%, transparent); color:var(--hw-warn); }
  .pill.heat { background:color-mix(in srgb, var(--hw-heat) 18%, transparent); color:var(--hw-heat); }
  .pill.ac { background:color-mix(in srgb, var(--hw-ac) 18%, transparent); color:var(--hw-ac); }
  .status-actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .hint { color:var(--secondary-text-color); font-size:13px; margin:0 4px 12px; }
  .btn { border:none; border-radius:999px; padding:9px 16px; font:inherit; font-weight:500; cursor:pointer; }
  .btn.primary { background:var(--primary-color); color:var(--text-primary-color, #fff); }
  .btn.danger { background:var(--hw-heat); color:#fff; }
  .btn.ghost { background:none; border:1px solid var(--divider-color); color:var(--primary-text-color); }
  .toggle { display:inline-flex; align-items:center; gap:8px; background:none; border:none; color:inherit; font:inherit; cursor:pointer; padding:4px; }
  .toggle .knob { width:36px; height:20px; border-radius:10px; background:var(--disabled-color, #9e9e9e); position:relative; transition:background .2s; }
  .toggle .knob::after { content:""; position:absolute; top:2px; left:2px; width:16px; height:16px; border-radius:50%; background:#fff; transition:left .2s; }
  .toggle.on .knob { background:var(--primary-color); }
  .toggle.on .knob::after { left:18px; }
  .hero { display:grid; grid-template-columns: 1.3fr 1fr; gap:24px; align-items:center; }
  .hero-head, .zone-head { display:flex; align-items:center; gap:8px; font-size:16px; font-weight:500; }
  .hero-head ha-icon, .zone-head ha-icon { color:var(--secondary-text-color); }
  .hero-temp { font-size:64px; font-weight:300; line-height:1.1; margin:10px 0 8px; letter-spacing:-.02em; }
  .decision { display:flex; gap:8px; align-items:flex-start; color:var(--secondary-text-color); font-size:14px; line-height:1.4; }
  .decision ha-icon { --mdc-icon-size:18px; flex:none; color:var(--primary-color); }
  .manual { display:flex; align-items:center; gap:6px; font-size:13px; color:var(--hw-warn); margin-top:8px; }
  .manual ha-icon { --mdc-icon-size:16px; }
  .hero-side { display:flex; flex-direction:column; gap:16px; align-items:center; }
  .badge { margin-left:auto; display:inline-flex; align-items:center; gap:4px; font-size:12px; font-weight:500; padding:3px 9px; border-radius:999px;
    background:var(--secondary-background-color); color:var(--secondary-text-color); }
  .badge ha-icon { --mdc-icon-size:14px; color:inherit !important; }
  .badge.heating { background:color-mix(in srgb, var(--hw-heat) 20%, transparent); color:var(--hw-heat); }
  .badge.off { opacity:.7; }
  .icon-btn { border:none; background:none; color:var(--disabled-color, #9e9e9e); cursor:pointer; padding:4px; border-radius:50%; display:flex; }
  .icon-btn.on { color:var(--hw-heat); }
  .icon-btn ha-icon { --mdc-icon-size:20px; color:inherit !important; }
  .tempctl { display:flex; align-items:center; gap:14px; margin:12px 0; }
  .tempctl .target { display:flex; flex-direction:column; align-items:center; min-width:72px; }
  .tempctl .label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--secondary-text-color); }
  .tempctl .val { font-size:24px; font-weight:500; }
  .tempctl.big .val { font-size:34px; }
  .round { width:40px; height:40px; border-radius:50%; border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--primary-text-color); font-size:22px; line-height:1; cursor:pointer; }
  .tempctl.big .round { width:48px; height:48px; font-size:26px; }
  .round:hover, .chip:hover, .tab:hover { border-color:var(--primary-color); }
  .presets { display:flex; flex-wrap:wrap; gap:6px; justify-content:center; }
  .chip { border:1px solid var(--divider-color); background:none; color:var(--primary-text-color); padding:5px 11px; border-radius:999px; font:inherit; font-size:13px; cursor:pointer; }
  .chip.active { background:var(--primary-color); border-color:var(--primary-color); color:var(--text-primary-color, #fff); }
  .stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin-top:12px; }
  .tile { display:flex; gap:12px; align-items:center; padding:14px 16px; }
  .tile ha-icon { color:var(--primary-color); }
  .tile-label { font-size:12px; color:var(--secondary-text-color); }
  .tile-val { font-size:20px; font-weight:500; }
  .tile-sub { font-size:12px; color:var(--secondary-text-color); display:flex; align-items:center; gap:5px; }
  .live { width:8px; height:8px; border-radius:50%; background:var(--hw-heat); animation:pulse 1.6s infinite; }
  @keyframes pulse { 0%{opacity:1} 50%{opacity:.3} 100%{opacity:1} }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:12px; }
  .zone { display:flex; flex-direction:column; }
  .zone.cold { border-color: color-mix(in srgb, var(--hw-ac) 45%, var(--divider-color)); }
  .zone-temps { margin-top:8px; }
  .zone-now { font-size:38px; font-weight:300; }
  .zone-why { font-size:13px; color:var(--secondary-text-color); min-height:18px; }
  .zone .tempctl { justify-content:center; margin-top:auto; padding-top:12px; }
  .legend { display:flex; flex-wrap:wrap; gap:14px; font-size:13px; color:var(--secondary-text-color); margin-bottom:10px; }
  .lg { display:inline-flex; align-items:center; gap:6px; }
  .sw { width:14px; height:3px; border-radius:2px; display:inline-block; }
  .sw.room { background:var(--primary-color); }
  .sw.target { background:var(--hw-heat); }
  .sw.outdoor { background:var(--secondary-text-color); opacity:.6; }
  .sw.band { height:10px; background:color-mix(in srgb, var(--hw-heat) 25%, transparent); }
  .chart { display:flex; gap:6px; }
  .ylabels { position:relative; width:30px; height:240px; font-size:11px; color:var(--secondary-text-color); }
  .ylab { position:absolute; right:0; transform:translateY(-50%); }
  .plot { flex:1; position:relative; }
  .plot svg { width:100%; height:240px; display:block; overflow:visible; }
  .plot path { fill:none; vector-effect:non-scaling-stroke; stroke-linejoin:round; }
  .plot path.room { stroke:var(--primary-color); stroke-width:2.5; }
  .plot path.target { stroke:var(--hw-heat); stroke-width:2; stroke-dasharray:6 4; }
  .plot path.outdoor { stroke:var(--secondary-text-color); stroke-width:1.5; opacity:.55; }
  .plot .grid { stroke:var(--divider-color); stroke-width:1; vector-effect:non-scaling-stroke; }
  .plot .band { fill:color-mix(in srgb, var(--hw-heat) 18%, transparent); }
  .xlabels { position:relative; height:20px; font-size:11px; color:var(--secondary-text-color); }
  .xlab { position:absolute; top:4px; transform:translateX(-50%); white-space:nowrap; }
  .xlab:first-child { transform:none; }
  .xlab:last-child { transform:translateX(-100%); }
  @media (max-width: 760px) {
    .content { padding:12px; }
    .hero { grid-template-columns:1fr; gap:8px; }
    .hero-temp { font-size:52px; }
    .status-actions { width:100%; justify-content:space-between; }
  }
`;

if (!customElements.get("heatwise-panel")) customElements.define("heatwise-panel", HeatWisePanel);
