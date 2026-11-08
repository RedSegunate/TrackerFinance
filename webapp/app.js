/* Tracker Finance — Mini App.
   Дизайн: /assets/design-system.css (папка «Design code»).
   Работает с тем же API, что и раньше: /api/app/*. */
"use strict";

/* ===================== Telegram ===================== */
const tg = window.Telegram && window.Telegram.WebApp;
const inTelegram = Boolean(tg && tg.initData);
const useTgMain = Boolean(inTelegram && tg.MainButton);
const tgTry = (fn) => { try { return fn(); } catch (_) { return undefined; } };

if (tg) {
  tgTry(() => tg.ready());
  tgTry(() => tg.expand());
  tgTry(() => tg.disableVerticalSwipes && tg.disableVerticalSwipes());
}

const headers = { "Content-Type": "application/json" };
if (inTelegram) headers["X-Telegram-Init-Data"] = tg.initData;

/* ===================== Мелочи ===================== */
const NB = " ";
const $ = (id) => document.getElementById(id);
const root = document.documentElement;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function store(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { /* ничего */ }
  return null;
}

/* Деньги: неразрывные пробелы, всегда по модулю. Знак добавляем сами. */
function fmtNum(value) {
  const n = Math.abs(Number(value) || 0);
  const text = Math.abs(n - Math.round(n)) > 0.004 ? n.toFixed(2).replace(".", ",") : String(Math.round(n));
  const [int, frac] = text.split(",");
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, NB) + (frac ? "," + frac : "");
}
const money = (v) => fmtNum(v) + NB + "₽";
const smoney = (v) => (Number(v) < 0 ? "−" : "") + money(v);       // только минус
const msign = (v) => (Number(v) < 0 ? "−" : "+") + money(v);        // плюс или минус
const compact = (v) => (v >= 1000 ? `${(Math.round(v / 100) / 10).toString().replace(".", ",")}${NB}тыс` : String(Math.round(v)));

const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const MONTHS_FULL = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

/* Категории: [эмодзи, номер цвета из --cat-N] */
const CAT = {
  "Продукты": ["🛒", 1], "Кафе и рестораны": ["☕", 2], "Транспорт": ["🚕", 3], "Авто": ["🚘", 8],
  "Жильё": ["🏠", 4], "Связь и интернет": ["📶", 7], "Здоровье": ["💊", 7], "Одежда": ["👕", 8],
  "Красота": ["💅", 5], "Развлечения": ["🎮", 5], "Подписки": ["🔁", 9], "Образование": ["🎓", 1],
  "Семья и дети": ["👨‍👩‍👧", 11], "Подарки": ["🎁", 11], "Путешествия": ["✈️", 4], "Бизнес-расходы": ["💼", 6],
  "Зарплата": ["💵", 12], "Подработка": ["🛠", 6], "Бизнес": ["💼", 3], "Подарок": ["🎁", 11], "Другое": ["📦", 10],
};
const catMeta = (c) => CAT[c] || CAT["Другое"];
const catIco = (c) => `<span class="cat-ico" style="--c:var(--cat-${catMeta(c)[1]})">${catMeta(c)[0]}</span>`;
const DONUT_ORDER = [1, 2, 5, 4, 3, 7, 8, 9, 6, 11, 12, 10];

const IC = {
  home: '<svg class="ic" viewBox="0 0 24 24"><path d="M3.5 11.2 12 4l8.5 7.2"/><path d="M5.8 9.8V20h12.4V9.8"/></svg>',
  list: '<svg class="ic" viewBox="0 0 24 24"><path d="M8 6.5h12M8 12h12M8 17.5h12"/><circle cx="4.2" cy="6.5" r=".6"/><circle cx="4.2" cy="12" r=".6"/><circle cx="4.2" cy="17.5" r=".6"/></svg>',
  plus: '<svg class="ic" viewBox="0 0 24 24" style="stroke-width:2.4"><path d="M12 5v14M5 12h14"/></svg>',
  chart: '<svg class="ic" viewBox="0 0 24 24"><path d="M5 20v-8M12 20V4M19 20v-5"/></svg>',
  spark: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3.5l2.1 5.2 5.4 2.1-5.4 2.1L12 18.1l-2.1-5.2-5.4-2.1 5.4-2.1z"/><path d="M19 4v3M17.5 5.5h3"/></svg>',
  down: '<svg class="ic" viewBox="0 0 24 24" style="width:20px;height:20px"><path d="M12 4v11M7.5 11 12 15.5 16.5 11M5 20h14"/></svg>',
  sliders: '<svg class="ic" viewBox="0 0 24 24" style="width:20px;height:20px"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>',
  trash: '<svg class="ic" viewBox="0 0 24 24" style="width:22px;height:22px"><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12.5h9.4L17.5 7M10 11v5M14 11v5"/></svg>',
};

/* ===================== Состояние ===================== */
const S = {
  me: null, settings: {}, timezones: [],
  cats: { expense: [], income: [] },
  screen: "home", dirty: {}, loading: {},
  hide: store("tf.hide") === "1",
  homePeriod: "month", monthStats: null, periodStats: {},
  recent: [], budgets: [], goals: [],
  statsPeriod: "month", statsKind: "expense",
  hKind: "all", hCat: "", hQ: "", hItems: [], hOffset: 0, hMore: false,
  txMap: new Map(),
  tipHidden: false,
  chat: [], aiBusy: false,
  sheetOpen: false, mainAction: null,
  toastTimer: null,
};
const SCREENS = ["home", "history", "stats", "plans", "ai", "settings"];
const TABS = [["home", IC.home, "Главная"], ["history", IC.list, "Операции"], ["add", IC.plus, ""], ["stats", IC.chart, "Аналитика"], ["ai", IC.spark, "Советник"]];

/* ===================== Сеть ===================== */
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) throw new Error(data.error || `Ошибка запроса (${response.status})`);
  return data;
}
const post = (path, body, method = "POST") => api(path, { method, body: JSON.stringify(body || {}) });

/* ===================== Telegram-помощники ===================== */
function haptic(kind = "success") {
  if (!inTelegram || !tg.HapticFeedback) return;
  tgTry(() => {
    if (kind === "tap") tg.HapticFeedback.selectionChanged();
    else if (kind === "light") tg.HapticFeedback.impactOccurred("light");
    else tg.HapticFeedback.notificationOccurred(kind);
  });
}
function confirmAction(message) {
  if (inTelegram && tg.showConfirm) return new Promise((resolve) => tgTry(() => tg.showConfirm(message, resolve)) ?? resolve(window.confirm(message)));
  return Promise.resolve(window.confirm(message));
}

function applyScheme() {
  const scheme = tg && tg.colorScheme;
  if (scheme) root.dataset.scheme = scheme; else root.removeAttribute("data-scheme");
}
function applyTheme(theme) {
  if (theme === "light" || theme === "dark") root.dataset.theme = theme; else root.removeAttribute("data-theme");
  applyScheme();
  if (!tg) return;
  const hex = theme === "light" ? "#F2F4F7" : theme === "dark" ? "#0D1216" : "secondary_bg_color";
  tgTry(() => tg.setHeaderColor(hex));
  tgTry(() => tg.setBackgroundColor(hex));
  tgTry(() => tg.setBottomBarColor && tg.setBottomBarColor(theme === "light" ? "#FFFFFF" : theme === "dark" ? "#162026" : "bottom_bar_bg_color"));
}

function syncTgButtons() {
  if (!inTelegram) return;
  const needBack = S.sheetOpen || S.screen === "plans" || S.screen === "settings";
  if (tg.BackButton) tgTry(() => (needBack ? tg.BackButton.show() : tg.BackButton.hide()));
  if (tg.SettingsButton) tgTry(() => tg.SettingsButton.show());
}
function setMain(text, enabled = true) {
  if (!useTgMain) return;
  tgTry(() => {
    if (!text) { tg.MainButton.hide(); return; }
    tg.MainButton.setText(text);
    if (enabled) tg.MainButton.enable(); else tg.MainButton.disable();
    tg.MainButton.show();
  });
}

/* ===================== Тосты, шторки ===================== */
function toast(message, undoId = null) {
  clearTimeout(S.toastTimer);
  const undo = undoId !== null ? `<button data-undo="${esc(undoId)}">Отменить</button>` : "";
  $("toast-host").innerHTML = `<div class="toast" role="status"><span>${esc(message)}</span>${undo}</div>`;
  S.toastTimer = setTimeout(() => { $("toast-host").innerHTML = ""; }, undoId === null ? 3000 : 7000);
}

function openSheet(html) {
  const ov = $("overlay");
  ov.innerHTML = `<div class="sheet" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div>`;
  ov.classList.add("open");
  S.sheetOpen = true;
  syncTgButtons();
}
function closeSheet() {
  const ov = $("overlay");
  ov.classList.remove("open");
  ov.innerHTML = "";
  S.sheetOpen = false;
  S.mainAction = null;
  setMain(null);
  if (inTelegram && tg.disableClosingConfirmation) tgTry(() => tg.disableClosingConfirmation());
  syncTgButtons();
}

/* ===================== Навигация ===================== */
function renderTabbar() {
  const on = S.screen === "plans" || S.screen === "settings" ? "home" : S.screen;
  $("tabbar").innerHTML = TABS.map(([id, icon, label]) =>
    `<button data-tab="${id}" class="${id === "add" ? "add" : ""} ${on === id ? "on" : ""}" ${id === "add" ? 'aria-label="Добавить операцию"' : ""}><span class="ti">${icon}</span>${label ? `<span>${label}</span>` : ""}</button>`
  ).join("");
}

function markDirty() { SCREENS.forEach((id) => { S.dirty[id] = true; }); }

function show(id, { force = false } = {}) {
  S.screen = id;
  $("login").classList.remove("on");
  SCREENS.forEach((name) => $("sc-" + name).classList.toggle("on", name === id));
  $("tabbar").hidden = false;
  renderTabbar();
  syncTgButtons();
  if (force || S.dirty[id] !== false) load(id);
  window.scrollTo(0, 0);
}

const LOADERS = {
  home: () => loadHome(), history: () => loadHistory(true), stats: () => loadStats(),
  plans: () => loadPlans(), settings: () => loadSettings(), ai: async () => renderChat(),
};
function load(id) {
  if (S.loading[id]) return;
  S.loading[id] = true;
  LOADERS[id]()
    .then(() => { S.dirty[id] = false; })
    .catch((error) => { toast(error.message); showFailure(id, error.message); })
    .finally(() => { S.loading[id] = false; });
}
function showFailure(id, message) {
  const box = id === "history" ? $("tx-list") : $("sc-" + id);
  if (!box || id === "ai") return;
  box.innerHTML = `<div class="empty"><span class="em-ico">⚠️</span><b>Не получилось загрузить</b><span class="muted">${esc(message)}</span><button class="btn secondary sm" data-act="retry">Повторить</button></div>`;
}
function skeleton(count = 4) { return Array.from({ length: count }, () => '<div class="skeleton"></div>').join(""); }

/* ===================== Общие куски разметки ===================== */
function dayLabel(date) {
  const parsed = new Date(`${date}T00:00:00`);
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (parsed.toDateString() === today.toDateString()) return "Сегодня";
  if (parsed.toDateString() === yesterday.toDateString()) return "Вчера";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: parsed.getFullYear() === today.getFullYear() ? undefined : "numeric" }).format(parsed);
}

function txRow(t, swipe) {
  const time = String(t.datetime || "").slice(11, 16);
  const amount = `<span class="amt ${t.kind === "income" ? "pos" : ""}">${t.kind === "income" ? "+" : "−"}${money(t.amount)}</span>`;
  const row = `<button class="row" data-tx="${t.id}">${catIco(t.category)}<span class="main"><b>${esc(t.note || t.category)}</b><span>${esc(t.category)}${time ? " · " + time : ""}</span></span>${amount}</button>`;
  return swipe ? `<div class="swipe-wrap">${row}<button class="swipe-act" data-del="${t.id}" aria-label="Удалить">${IC.trash}</button></div>` : row;
}
function txList(items, swipe) {
  items.forEach((t) => S.txMap.set(String(t.id), t));
  let html = "", prev = "";
  const dayTotal = {};
  items.forEach((t) => { const d = String(t.datetime || "").slice(0, 10); dayTotal[d] = (dayTotal[d] || 0) + (t.kind === "income" ? t.amount : -t.amount); });
  items.forEach((t) => {
    const d = String(t.datetime || "").slice(0, 10);
    if (d !== prev) {
      html += `<div class="date-head"><span>${esc(d ? dayLabel(d) : "Дата не указана")}</span><span class="num amt">${msign(dayTotal[d])}</span></div>`;
      prev = d;
    }
    html += txRow(t, swipe);
  });
  return html;
}
const emptyBlock = (icon, title, text, button = "") =>
  `<div class="empty"><span class="em-ico">${icon}</span><b>${esc(title)}</b>${text ? `<span class="muted">${esc(text)}</span>` : ""}${button}</div>`;

const progressClass = (pct) => (pct >= 100 ? "over" : pct >= 80 ? "warn" : "");
const pctClass = (pct) => (pct >= 100 ? "neg" : pct >= 80 ? "warn" : "");

function goalRows(goals, full) {
  if (!goals.length) return `<div class="card">${emptyBlock("🎯", "Целей пока нет", "Назовите цель и сумму — приложение покажет прогресс.", '<button class="btn primary sm" data-act="goal-new">Создать цель</button>')}</div>`;
  return `<div class="card flush list">${goals.map((g) => {
    const left = Math.max(0, g.target - g.saved);
    return `<div class="row" style="align-items:flex-start;padding-top:12px;padding-bottom:12px"><span class="cat-ico" style="--c:var(--cat-1);font-size:22px">${esc(g.icon || "🎯")}</span>
      <span class="main"><b>${esc(g.title)}</b><span class="num amt">${money(g.saved)} из ${money(g.target)}</span>
      <div class="progress" style="margin-top:8px"><i style="width:${g.pct}%"></i></div>
      ${full ? `<span class="wrap num amt" style="margin-top:6px">${left ? "Осталось " + money(left) : "Цель достигнута 🎉"}</span><div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm secondary" data-goal-add="${g.id}">+ Пополнить</button><button class="btn sm ghost" data-goal-del="${g.id}">Удалить</button></div>` : ""}</span>
      <b class="num" style="color:var(--accent)">${g.pct}%</b></div>`;
  }).join("")}</div>`;
}

/* ===================== Графики (SVG) ===================== */
function niceMax(v) {
  if (v <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

function barChart(rows) {     // rows: [подпись, доход, расход]
  const W = 330, H = 150, pb = 22, pt = 8;
  const max = niceMax(Math.max(...rows.map((r) => Math.max(r[1], r[2])), 1));
  const n = rows.length, bw = 14, slot = (W - 8) / n;
  let g = "";
  let labels = "";
  [0, 0.5, 1].forEach((k) => {
    const y = pt + (H - pb - pt) * (1 - k);
    g += `<line class="grid" x1="0" x2="${W}" y1="${y}" y2="${y}"/>`;
    if (k) labels += `<text class="axis" x="0" y="${y - 3}">${compact(max * k)}</text>`;
  });
  rows.forEach((r, i) => {
    const x = 4 + i * slot + (slot - (bw * 2 + 4)) / 2;
    const h1 = (H - pb - pt) * r[1] / max, h2 = (H - pb - pt) * r[2] / max;
    g += `<rect class="bar-inc" x="${x}" y="${H - pb - h1}" width="${bw}" height="${Math.max(h1, r[1] ? 2 : 0)}" rx="4"/>`;
    g += `<rect class="bar-exp" x="${x + bw + 4}" y="${H - pb - h2}" width="${bw}" height="${Math.max(h2, r[2] ? 2 : 0)}" rx="4"/>`;
    g += `<text class="axis" x="${x + bw + 2}" y="${H - 6}" text-anchor="middle">${esc(r[0])}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Доходы и расходы по месяцам">${g}${labels}</svg>`;
}

function seriesChart(series, kind) {   // один ряд столбиков: день / неделя / год
  const W = 330, H = 150, pb = 22, pt = 8;
  const max = niceMax(Math.max(...series.map((s) => s.amount), 1));
  const n = series.length, slot = (W - 8) / n, bw = Math.max(3, Math.min(22, slot - 3));
  const every = n > 24 ? 5 : n > 12 ? 4 : 1;
  let g = "";
  let labels = "";
  [0, 0.5, 1].forEach((k) => {
    const y = pt + (H - pb - pt) * (1 - k);
    g += `<line class="grid" x1="0" x2="${W}" y1="${y}" y2="${y}"/>`;
    if (k) labels += `<text class="axis" x="0" y="${y - 3}">${compact(max * k)}</text>`;
  });
  series.forEach((s, i) => {
    const x = 4 + i * slot + (slot - bw) / 2, h = (H - pb - pt) * s.amount / max;
    g += `<rect class="${kind === "income" ? "bar-inc" : "bar-exp"}" x="${x}" y="${H - pb - h}" width="${bw}" height="${Math.max(h, s.amount ? 2 : 0)}" rx="${Math.min(4, bw / 2)}"><title>${esc(s.label)}: ${money(s.amount)}</title></rect>`;
    if (i % every === 0) g += `<text class="axis" x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(s.label)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Динамика">${g}${labels}</svg>`;
}

function lineChart(cum, daysTotal, budget) {   // расходы нарастающим итогом, прогноз, лимит
  const W = 330, H = 170, pl = 6, pr = 6, pt = 14, pb = 22;
  const last = cum[cum.length - 1] || 0;
  const perDay = cum.length ? last / cum.length : 0;
  const endV = perDay * daysTotal;
  const max = niceMax(Math.max(budget || 0, endV, last, 1) * 1.05);
  const X = (d) => pl + (W - pl - pr) * (d / Math.max(1, daysTotal - 1));
  const Y = (v) => pt + (H - pt - pb) * (1 - v / max);
  const pts = cum.map((v, i) => [X(i), Y(v)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const lp = pts[pts.length - 1] || [X(0), Y(0)];
  const now = new Date(), mi = now.getMonth();
  let g = "";
  [0, 0.5, 1].forEach((k) => g += `<line class="grid" x1="0" x2="${W}" y1="${Y(max * k)}" y2="${Y(max * k)}"/>${k ? `<text class="axis" x="0" y="${Y(max * k) - 3}">${compact(max * k)}</text>` : ""}`);
  if (budget) {
    g += `<line x1="0" x2="${W}" y1="${Y(budget)}" y2="${Y(budget)}" stroke="var(--warn)" stroke-width="1.5" stroke-dasharray="2 4"/>`;
    g += `<text class="axis" x="${W}" y="${Y(budget) - 5}" text-anchor="end" style="fill:var(--warn)">бюджет ${compact(budget)}</text>`;
  }
  if (pts.length) g += `<path class="area" d="${line} L${lp[0]} ${Y(0)} L${pts[0][0]} ${Y(0)} Z"/><path class="line" d="${line}"/>`;
  if (cum.length < daysTotal) g += `<path class="forecast" d="M${lp[0]} ${lp[1]} L${X(daysTotal - 1)} ${Y(endV)}"/>`;
  g += `<circle class="dot" cx="${lp[0]}" cy="${lp[1]}" r="6"/>`;
  g += `<text class="axis" x="${X(0)}" y="${H - 6}">1 ${MONTHS_SHORT[mi]}</text><text class="axis" x="${X(daysTotal - 1)}" y="${H - 6}" text-anchor="end">${daysTotal} ${MONTHS_SHORT[mi]}</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Расходы нарастающим итогом и прогноз">${g}</svg>`;
}

function donut(rows, total, label) {
  let a = 0;
  const stops = rows.map((r, i) => { const s = a; a += total ? r.amount / total * 100 : 0; return `var(--cat-${DONUT_ORDER[i % DONUT_ORDER.length]}) ${s}% ${a}%`; });
  return `<div class="donut" style="background:conic-gradient(${stops.join(",")}); --size:150px" role="img" aria-label="${esc(label)}"><div class="center"><div class="muted">${esc(label)}</div><b class="num amt" style="font-size:18px">${money(total)}</b></div></div>`;
}

/* ===================== ГЛАВНАЯ ===================== */
function safeToday() {
  const total = S.budgets.reduce((s, b) => s + b.limit, 0);
  if (!total) return null;
  const spent = S.budgets.reduce((s, b) => s + b.spent, 0);
  const now = new Date();
  const dim = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const left = dim - now.getDate() + 1;
  const rest = total - spent;
  return { total, spent, rest, left, perDay: Math.floor(Math.max(0, rest) / left), pct: Math.min(100, spent / total * 100) };
}

function daysWord(n) { return n % 10 === 1 && n % 100 !== 11 ? "день" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "дня" : "дней"; }

function homeTip() {
  if (S.tipHidden) return "";
  const hot = S.budgets.slice().sort((a, b) => b.pct - a.pct)[0];
  let title = "", text = "", action = true;
  if (hot && hot.pct >= 80) {
    title = hot.pct >= 100 ? `${hot.category}: лимит превышен` : `${hot.category} почти на пределе`;
    text = `Потрачено ${money(hot.spent)} из ${money(hot.limit)}.`;
  } else if (S.monthStats && S.monthStats.insights && S.monthStats.insights[0]) {
    title = "Наблюдение"; text = S.monthStats.insights[0]; action = false;
  } else return "";
  return `<div class="tip" style="margin-top:12px"><span class="ico">💡</span><div><b>${esc(title)}</b><div class="muted" style="margin-top:2px">${esc(text)}</div>
    <div class="acts">${action ? '<button class="btn sm primary" data-act="plans">Изменить лимит</button>' : ""}<button class="btn sm ghost" data-act="tip-hide">Позже</button></div></div></div>`;
}

function summaryHtml() {
  const p = S.periodStats[S.homePeriod];
  if (!p) return skeleton(2);
  const diff = p.income - p.expense;
  return `<div><div class="muted">Доходы</div><b class="pos num amt">+${money(p.income)}</b></div>
    <div><div class="muted">Расходы</div><b class="neg num amt">−${money(p.expense)}</b></div>
    <div><div class="muted">Разница</div><b class="num amt ${diff < 0 ? "neg" : "pos"}">${msign(diff)}</b></div>`;
}

function renderHome() {
  const m = S.monthStats, sp = safeToday();
  const hr = new Date().getHours();
  const greet = hr < 5 ? "Доброй ночи" : hr < 12 ? "Доброе утро" : hr < 18 ? "Добрый день" : "Добрый вечер";
  const budgetCards = S.budgets.length
    ? `<div class="h-scroll">${S.budgets.map((b) => `<div class="budget-card"><div style="display:flex;justify-content:space-between;align-items:center">${catIco(b.category)}<b class="num ${pctClass(b.pct)}">${b.pct}%</b></div><b style="font-size:13px">${esc(b.category)}</b><div class="progress ${progressClass(b.pct)}"><i style="width:${Math.min(100, b.pct)}%"></i></div><span class="muted num amt">${money(b.spent)} / ${money(b.limit)}</span></div>`).join("")}</div>`
    : `<div class="card">${emptyBlock("◷", "Лимитов пока нет", "Поставьте лимит на категорию — приложение предупредит заранее.", '<button class="btn primary sm" data-act="plans">Создать бюджет</button>')}</div>`;

  $("sc-home").innerHTML = `
  <div class="topbar"><div class="title"><span class="muted">${greet}</span><h1>${esc(S.me.display_name || "Твои финансы")}</h1></div>
    <div class="actions"><button class="icon-btn" data-act="eye" aria-label="${S.hide ? "Показать суммы" : "Скрыть суммы"}" aria-pressed="${S.hide}">${S.hide ? "🙈" : "👁"}</button><button class="icon-btn" data-act="settings" aria-label="Настройки">${IC.sliders}</button></div></div>
  <section class="hero ${S.hide ? "hidden" : ""}">
    <div class="label"><span>Общий баланс</span></div>
    <div class="value num">${smoney(S.me.overall_balance)}</div>
    <span class="delta amt">${m.balance >= 0 ? "▲" : "▼"} ${msign(m.balance)} за месяц</span>
    <div class="split"><div><small>Доходы за месяц</small><b class="num amt">+${money(m.income)}</b></div><div><small>Расходы за месяц</small><b class="num amt">−${money(m.expense)}</b></div></div>
  </section>
  <div class="quick">
    <button data-act="add-exp"><span class="ico exp">−</span>Расход</button>
    <button data-act="add-inc"><span class="ico inc">+</span>Доход</button>
    <button data-act="plans"><span class="ico acc">◎</span>Цели</button>
    <button data-act="ai"><span class="ico inf">✦</span>Совет</button>
  </div>
  ${sp ? `<div class="card" style="margin-top:12px"><div class="safe"><span class="muted">${sp.rest >= 0 ? "Можно тратить в день" : "Бюджет месяца превышен"}</span><b class="num amt ${sp.rest < 0 ? "neg" : ""}">${sp.rest >= 0 ? money(sp.perDay) : "−" + money(-sp.rest)}</b>
    <span class="muted num amt" style="grid-column:1/-1">До конца месяца ${sp.left} ${daysWord(sp.left)} · осталось ${smoney(sp.rest)} из ${money(sp.total)}</span></div>
    <div class="progress ${progressClass(sp.pct)}" style="margin-top:10px"><i style="width:${sp.pct}%"></i></div></div>` : ""}
  ${homeTip()}
  <div class="section-head"><h2>Сводка</h2></div>
  <div class="segmented" id="seg-period">${[["today", "День"], ["week", "Неделя"], ["month", "Месяц"]].map(([k, n]) => `<button data-p="${k}" class="${S.homePeriod === k ? "on" : ""}">${n}</button>`).join("")}</div>
  <div class="card" id="home-summary" style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">${summaryHtml()}</div>
  <div class="section-head"><h2>Последние операции</h2><button class="link" data-act="history">Все</button></div>
  <div class="card flush list">${S.recent.length ? S.recent.slice(0, 3).map((t) => { S.txMap.set(String(t.id), t); return txRow(t, false); }).join("") : emptyBlock("🧾", "Операций пока нет", "Нажмите «＋», чтобы добавить первую.", '<button class="btn primary sm" data-act="add-exp">Добавить операцию</button>')}</div>
  <div class="section-head"><h2>Бюджеты</h2><button class="link" data-act="plans">Все</button></div>
  ${budgetCards}
  <div class="section-head"><h2>Цели</h2><button class="link" data-act="plans">Все</button></div>
  ${goalRows(S.goals.slice(0, 2), false)}`;
}

async function loadHome() {
  if (!S.monthStats) $("sc-home").innerHTML = skeleton(6);
  const [month, tx, budgets, goals, me] = await Promise.all([
    api("/api/app/stats?period=month"), api("/api/app/transactions"),
    api("/api/app/budgets"), api("/api/app/goals"), api("/api/app/me"),
  ]);
  S.me = { ...S.me, ...me };
  S.monthStats = month;
  S.periodStats = { ...S.periodStats, month };
  S.recent = tx.items; S.budgets = budgets.items; S.goals = goals.items;
  if (S.homePeriod !== "month") S.periodStats[S.homePeriod] = await api(`/api/app/stats?period=${S.homePeriod}`);
  renderHome();
}

async function setHomePeriod(period) {
  S.homePeriod = period;
  document.querySelectorAll("#seg-period button").forEach((b) => b.classList.toggle("on", b.dataset.p === period));
  if (!S.periodStats[period] || period !== "month") {
    try { S.periodStats[period] = await api(`/api/app/stats?period=${period}`); } catch (e) { toast(e.message); return; }
  }
  const box = $("home-summary");
  if (box && S.homePeriod === period) box.innerHTML = summaryHtml();
}

/* ===================== ОПЕРАЦИИ ===================== */
async function loadHistory(reset = true) {
  if (reset) { S.hItems = []; S.hOffset = 0; $("tx-list").innerHTML = skeleton(4); $("tx-more").innerHTML = ""; }
  const params = new URLSearchParams({ kind: S.hKind, offset: String(S.hOffset) });
  if (S.hQ) params.set("q", S.hQ);
  if (S.hCat) params.set("category", S.hCat);
  const data = await api(`/api/app/transactions?${params}`);
  S.hItems.push(...data.items);
  S.hOffset = data.next_offset; S.hMore = data.has_more;
  $("tx-list").innerHTML = S.hItems.length
    ? txList(S.hItems, true)
    : emptyBlock("🔍", S.hQ || S.hCat || S.hKind !== "all" ? "Ничего не найдено" : "Операций пока нет", S.hQ || S.hCat ? "Попробуйте другое слово или сбросьте фильтры." : "Нажмите «＋», чтобы добавить первую.");
  $("tx-more").innerHTML = S.hMore ? '<button class="btn secondary block" style="margin-top:12px" data-act="more">Показать ещё</button>' : "";
  $("history-cat").classList.toggle("on", Boolean(S.hCat));
  $("history-cat").textContent = S.hCat ? `${catMeta(S.hCat)[0]} ${S.hCat} ✕` : "🏷 Категория ▾";
}

function pickCategoryFilter() {
  const all = [...new Set([...S.cats.expense, ...S.cats.income])];
  openSheet(`<h2>Категория</h2><div class="card flush list" style="box-shadow:none">
    <button class="row" data-cat-filter=""><span class="cat-ico">🗂</span><span class="main"><b>Все категории</b></span></button>
    ${all.map((c) => `<button class="row" data-cat-filter="${esc(c)}">${catIco(c)}<span class="main"><b>${esc(c)}</b></span></button>`).join("")}</div>`);
}

async function deleteTx(id) {
  try {
    const result = await api(`/api/app/transactions/${id}`, { method: "DELETE" });
    haptic("warning");
    closeSheet();
    toast("Операция удалена", result.undo_id);
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); }
}

/* ===================== ШТОРКА «ДОБАВИТЬ» ===================== */
const add = { kind: "expense", amount: "", cat: "", note: "", noteOpen: false, dt: "", dtTouched: false };

function localInput(date = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`;
}
function dtLabel(value) {
  const d = new Date(value);
  const time = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  const today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
  const day = d.toDateString() === today.toDateString() ? "Сегодня" : d.toDateString() === y.toDateString() ? "Вчера" : `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
  return `${day}, ${time}`;
}
function amountText(raw) {
  const [i, f] = (raw || "0").split(".");
  const intPart = (i || "0").replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  return raw && raw.includes(".") ? `${intPart},${f}` : intPart;
}

function openAdd(kind = "expense") {
  add.kind = kind; add.amount = ""; add.note = ""; add.noteOpen = false; add.dtTouched = false; add.dt = localInput();
  add.cat = S.cats[kind][0] || "";
  openSheet(`
    <div class="segmented" id="add-kind"><button data-k="expense">− Расход</button><button data-k="income">+ Доход</button></div>
    <div class="amount-display"><div class="big num"><span id="a-sign"></span><span id="a-val">0</span><span class="caret"></span><span class="cur">₽</span></div>
      <div class="muted" id="a-hint">Или напишите словами: «кофе 200»</div></div>
    <div class="cat-pick" id="add-cats"></div>
    <div style="display:flex;gap:8px;margin:8px 0;flex-wrap:wrap">
      <label class="chip dt" style="position:relative;overflow:hidden">📅 <span id="a-dt-label"></span><input id="a-dt" type="datetime-local" style="position:absolute;inset:0;opacity:0;width:100%;height:100%" /></label>
      <button class="chip" data-add-act="note">📝 Заметка</button>
      <button class="chip" data-add-act="words">✍️ Словами</button>
    </div>
    <input class="input" id="a-note" maxlength="100" placeholder="Заметка (необязательно)" hidden style="margin-bottom:8px" />
    <div class="numpad" id="numpad">${["1", "2", "3", "4", "5", "6", "7", "8", "9", ",", "0", "⌫"].map((k) => `<button data-n="${k}" aria-label="${k === "⌫" ? "Стереть" : k}">${k}</button>`).join("")}</div>
    ${useTgMain ? "" : '<button class="btn primary block" id="add-save" style="margin-top:12px" disabled>Введите сумму</button>'}`);
  S.mainAction = saveAdd;
  syncAdd(true);
}

function syncAdd(full = false) {
  if (!$("a-val")) return;
  const exp = add.kind === "expense";
  $("a-sign").textContent = exp ? "−" : "+";
  $("a-sign").style.color = exp ? "var(--expense)" : "var(--income)";
  $("a-val").textContent = amountText(add.amount);
  $("a-hint").hidden = Boolean(add.amount);
  $("a-dt-label").textContent = dtLabel(add.dt);
  if (full) {
    document.querySelectorAll("#add-kind button").forEach((b) => b.classList.toggle("on", b.dataset.k === add.kind));
    $("add-cats").innerHTML = S.cats[add.kind].map((c) => `<button data-c="${esc(c)}" class="${add.cat === c ? "on" : ""}">${catIco(c)}<span>${esc(c.length > 10 ? c.split(" ")[0] : c)}</span></button>`).join("");
    $("a-dt").value = add.dt;
  } else {
    document.querySelectorAll("#add-cats button").forEach((b) => b.classList.toggle("on", b.dataset.c === add.cat));
  }
  const value = Number(add.amount || 0);
  const label = value > 0 ? `Сохранить ${exp ? "−" : "+"}${money(value)}` : "Введите сумму";
  if (useTgMain) setMain(label, value > 0);
  else { const b = $("add-save"); if (b) { b.textContent = label; b.disabled = !(value > 0); } }
  if (inTelegram && tg.enableClosingConfirmation) tgTry(() => (value > 0 ? tg.enableClosingConfirmation() : tg.disableClosingConfirmation()));
}

function numpadPress(key) {
  let a = add.amount;
  if (key === "⌫") a = a.slice(0, -1);
  else if (key === ",") { if (!a.includes(".")) a = (a || "0") + "."; }
  else {
    const [i, f] = a.split(".");
    if (a.includes(".") ? f.length >= 2 : (i || "").length >= 9) return;
    a = a === "0" ? key : a + key;
  }
  add.amount = a;
  haptic("tap");
  syncAdd();
}

async function saveAdd() {
  const value = Number(add.amount || 0);
  if (!(value > 0)) return;
  setMain(useTgMain ? "Сохраняю…" : null, false);
  const btn = $("add-save"); if (btn) btn.disabled = true;
  try {
    const body = { kind: add.kind, amount: add.amount, category: add.cat, note: ($("a-note") ? $("a-note").value : add.note).trim() };
    if (add.dtTouched) body.datetime = add.dt;
    await post("/api/app/add", body);
    haptic("success");
    closeSheet();
    toast(`Записано: ${add.kind === "expense" ? "−" : "+"}${money(value)}`);
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); haptic("error"); syncAdd(); }
}

/* Быстрый ввод словами */
function openQuickText() {
  openSheet(`<h2>Напишите словами</h2><p class="muted">Например: «кофе 250», «такси 400 и продукты 1200».</p>
    <div class="field"><input class="input" id="q-text" maxlength="300" placeholder="кофе 250" autocomplete="off" /></div>
    <div class="acts-row"><button class="btn secondary" data-act="close-sheet">Отмена</button><button class="btn primary" id="q-go">Распознать</button></div>`);
  const input = $("q-text");
  if (input) input.focus();
}
async function runQuickText() {
  const text = $("q-text").value.trim();
  if (!text) return;
  $("q-go").disabled = true;
  try {
    const result = await post("/api/app/add", { text });
    if (!result.confirmed) { renderQuickPreview(result.items); return; }
    haptic("success"); closeSheet();
    toast(String(result.reply || "Записано").split("\n")[0]);
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); $("q-go").disabled = false; }
}
let quickItems = [];
function renderQuickPreview(items) {
  quickItems = items;
  openSheet(`<h2>Проверьте записи</h2><p class="muted">Выберите категорию там, где приложение не уверено.</p>
    ${items.map((it, i) => `<div class="field"><label>${it.kind === "income" ? "Доход" : "Расход"} · ${money(it.amount)} · ${esc(it.note || "без описания")}</label>
      <select class="input" data-qcat="${i}">${(S.cats[it.kind] || []).map((c) => `<option value="${esc(c)}"${c === it.category ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></div>`).join("")}
    <div class="acts-row"><button class="btn secondary" data-act="close-sheet">Отмена</button><button class="btn primary" id="q-ok">Сохранить</button></div>`);
}
async function confirmQuick() {
  const items = quickItems.map((it, i) => ({ ...it, uncertain: it.category === "Другое", category: document.querySelector(`[data-qcat="${i}"]`).value }));
  $("q-ok").disabled = true;
  try {
    const result = await post("/api/app/add", { items });
    haptic("success"); closeSheet();
    toast(String(result.reply || "Записано").split("\n")[0]);
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); $("q-ok").disabled = false; }
}

/* ===================== Изменение операции ===================== */
const edit = { id: 0, kind: "expense", cat: "" };
function openEdit(id) {
  const t = S.txMap.get(String(id));
  if (!t) return;
  edit.id = t.id; edit.kind = t.kind; edit.cat = t.category;
  openSheet(`
    <div class="segmented" id="edit-kind"><button data-ek="expense">− Расход</button><button data-ek="income">+ Доход</button></div>
    <div class="field"><label for="e-amount">Сумма, ₽</label><input class="input num" id="e-amount" inputmode="decimal" value="${esc(String(t.amount).replace(".", ","))}" /></div>
    <div class="field"><label>Категория</label><div class="cat-pick" id="edit-cats"></div></div>
    <div class="field"><label for="e-note">Описание</label><input class="input" id="e-note" maxlength="100" value="${esc(t.note)}" /></div>
    <div class="field"><label for="e-date">Дата и время</label><input class="input" id="e-date" type="datetime-local" value="${esc(String(t.datetime || "").slice(0, 16))}" /></div>
    <div class="acts-row"><button class="btn primary" data-act="edit-save">Сохранить</button><button class="btn danger" data-act="edit-del">Удалить</button></div>`);
  syncEdit();
}
function syncEdit() {
  document.querySelectorAll("#edit-kind button").forEach((b) => b.classList.toggle("on", b.dataset.ek === edit.kind));
  if (!S.cats[edit.kind].includes(edit.cat)) edit.cat = S.cats[edit.kind][0];
  $("edit-cats").innerHTML = S.cats[edit.kind].map((c) => `<button data-ec="${esc(c)}" class="${edit.cat === c ? "on" : ""}">${catIco(c)}<span>${esc(c.length > 10 ? c.split(" ")[0] : c)}</span></button>`).join("");
}
async function saveEdit() {
  try {
    const body = { kind: edit.kind, amount: $("e-amount").value, category: edit.cat, note: $("e-note").value };
    if ($("e-date").value) body.datetime = $("e-date").value;
    await post(`/api/app/transactions/${edit.id}`, body, "PATCH");
    haptic("success"); closeSheet(); toast("Операция обновлена");
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); }
}

/* ===================== АНАЛИТИКА ===================== */
function periodTitle(p) {
  const now = new Date();
  return { today: "Сегодня", week: "Эта неделя", month: `${MONTHS_FULL[now.getMonth()]} ${now.getFullYear()}`, year: `${now.getFullYear()} год` }[p];
}

async function loadStats() {
  if (!$("sc-stats").innerHTML.trim()) $("sc-stats").innerHTML = skeleton(6);
  const [cur, yExp, yInc, budgets] = await Promise.all([
    api(`/api/app/stats?period=${S.statsPeriod}&kind=${S.statsKind}`),
    api("/api/app/stats?period=year&kind=expense"), api("/api/app/stats?period=year&kind=income"),
    api("/api/app/budgets"),
  ]);
  S.budgets = budgets.items;
  renderStats(cur, yExp.series, yInc.series);
}

function renderStats(d, yExp, yInc) {
  const isExp = S.statsKind === "expense";
  const total = isExp ? d.expense : d.income;
  const cats = (isExp ? d.categories : d.income_categories) || [];
  const shown = cats.slice(0, 7);
  const rest = cats.slice(7).reduce((s, c) => s + c.amount, 0);
  if (rest > 0) shown.push({ category: "Остальное", amount: rest, share: total ? rest / total * 100 : 0 });
  const top = cats[0];
  const budgetTotal = S.budgets.reduce((s, b) => s + b.limit, 0);

  let flow = "";
  if (isExp && S.statsPeriod === "month") {
    const today = new Date().getDate();
    const cum = []; let run = 0;
    d.series.slice(0, today).forEach((s) => { run += s.amount; cum.push(run); });
    const dim = d.series.length;
    const forecast = cum.length ? (run / cum.length) * dim : 0;
    let banner = "";
    if (cum.length >= 3 && run > 0) {
      banner = budgetTotal && forecast > budgetTotal
        ? `<div class="banner" style="margin-top:10px">⚠️ <span class="amt">При таком темпе к концу месяца выйдет около <b>${money(forecast)}</b>, это на ${money(forecast - budgetTotal)} больше бюджета.</span></div>`
        : `<div class="banner" style="margin-top:10px">📈 <span class="amt">При таком темпе к концу месяца выйдет около <b>${money(forecast)}</b>${budgetTotal ? ", это в рамках бюджета" : ""}.</span></div>`;
    }
    flow = `<div class="section-head"><h2>Темп трат и прогноз</h2></div><div class="card">${lineChart(cum, dim, budgetTotal || null)}${banner}</div>`;
  } else if (d.series.some((s) => s.amount > 0)) {
    flow = `<div class="section-head"><h2>Динамика</h2></div><div class="card">${seriesChart(d.series, S.statsKind)}</div>`;
  }

  const now = new Date(), mi = now.getMonth();
  const from = Math.max(0, mi - 5);
  const months = [];
  for (let i = from; i <= mi; i++) months.push([MONTHS_SHORT[i], (yInc[i] || {}).amount || 0, (yExp[i] || {}).amount || 0]);
  const monthsBlock = months.some((r) => r[1] || r[2])
    ? `<div class="section-head"><h2>Доходы и расходы</h2><span class="muted">по месяцам</span></div><div class="card">${barChart(months)}<div style="display:flex;gap:16px;justify-content:center" class="muted"><span><b class="pos">■</b> Доходы</span><span><b class="neg">■</b> Расходы</span></div></div>`
    : "";

  $("sc-stats").innerHTML = `
  <div class="topbar"><div class="title"><span class="eyebrow">Обзор</span><h1>Аналитика</h1></div><div class="actions"><button class="icon-btn" data-act="export" aria-label="Скачать Excel">${IC.down}</button></div></div>
  <div class="segmented" id="stats-period">${[["today", "День"], ["week", "Неделя"], ["month", "Месяц"], ["year", "Год"]].map(([k, n]) => `<button data-sp="${k}" class="${S.statsPeriod === k ? "on" : ""}">${n}</button>`).join("")}</div>
  <div class="segmented" id="stats-kind" style="margin-top:8px"><button data-sk="expense" class="${isExp ? "on" : ""}">Расходы</button><button data-sk="income" class="${isExp ? "" : "on"}">Доходы</button></div>
  <div class="muted" style="margin:10px 2px 0">${esc(periodTitle(S.statsPeriod))}</div>
  ${cats.length ? `
  <div class="card" style="margin-top:8px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
    ${donut(shown, total, isExp ? "Расходы" : "Доходы")}
    <div style="display:grid;gap:8px;min-width:120px"><div><div class="muted">Самая большая</div><b>${catMeta(top.category)[0]} ${esc(top.category)}</b></div>
    <div><div class="muted">Баланс периода</div><b class="num amt ${d.balance < 0 ? "neg" : "pos"}">${msign(d.balance)}</b></div></div>
  </div>
  <div class="card" style="margin-top:12px">${shown.map((r, i) => `<div class="legend-row" style="--c:var(--cat-${DONUT_ORDER[i % DONUT_ORDER.length]})"><span class="sw"></span><div style="flex:1;min-width:0"><div style="display:flex;justify-content:space-between;gap:8px"><b>${catMeta(r.category)[0]} ${esc(r.category)}</b><b class="num amt">${money(r.amount)}</b></div><div class="bar"><i style="width:${total ? r.amount / total * 100 : 0}%"></i></div></div><span class="muted num" style="width:38px;text-align:right">${Math.round(r.share)}%</span></div>`).join("")}</div>`
  : `<div class="card" style="margin-top:8px">${emptyBlock("📊", "Пока нечего показывать", "За этот период нет операций.", '<button class="btn primary sm" data-act="add-exp">Добавить операцию</button>')}</div>`}
  ${flow}
  ${monthsBlock}
  ${d.insights && d.insights.length ? `<div class="section-head"><h2>Наблюдения</h2></div><div class="card flush list">${d.insights.map((t) => `<div class="row"><span class="cat-ico" style="--c:var(--accent)">💡</span><span class="main"><span class="wrap" style="color:var(--text)">${esc(t)}</span></span></div>`).join("")}</div>` : ""}`;
}

/* ===================== ПЛАНЫ: бюджеты и цели ===================== */
async function loadPlans() {
  if (!$("sc-plans").innerHTML.trim()) $("sc-plans").innerHTML = skeleton(5);
  const [budgets, goals] = await Promise.all([api("/api/app/budgets"), api("/api/app/goals")]);
  S.budgets = budgets.items; S.goals = goals.items;
  renderPlans();
}

function renderPlans() {
  const sp = safeToday();
  const rows = S.budgets.map((b) => {
    const left = b.limit - b.spent;
    return `<button class="row" data-budget="${esc(b.category)}" style="align-items:flex-start;padding-top:12px;padding-bottom:12px">${catIco(b.category)}<span class="main"><b>${esc(b.category)}</b><span class="num amt">${money(b.spent)} из ${money(b.limit)}</span>
      <div class="progress ${progressClass(b.pct)}" style="margin-top:8px"><i style="width:${Math.min(100, b.pct)}%"></i></div>
      <span class="amt" style="margin-top:6px;color:${b.pct >= 100 ? "var(--expense)" : "var(--hint)"}">${left >= 0 ? "Осталось " + money(left) : "Превышен на " + money(-left)}</span></span>
      <b class="num ${pctClass(b.pct)}">${b.pct}%</b></button>`;
  }).join("");
  $("sc-plans").innerHTML = `
  <div class="topbar"><div class="title"><span class="eyebrow">Планирование</span><h1>Бюджеты и цели</h1></div></div>
  ${sp ? `<div class="card"><div class="safe"><span class="muted">Общий бюджет на месяц</span><b class="num amt">${money(sp.total)}</b><span class="muted num amt">Потрачено ${money(sp.spent)} · ${sp.rest >= 0 ? "осталось " + money(sp.rest) : "превышен на " + money(-sp.rest)}</span><span class="muted" style="text-align:right">${Math.round(sp.spent / sp.total * 100)}%</span></div><div class="progress ${progressClass(sp.spent / sp.total * 100)}" style="margin-top:10px"><i style="width:${sp.pct}%"></i></div></div>` : ""}
  <div class="section-head"><h2>По категориям</h2><button class="link" data-act="budget-new">Добавить</button></div>
  ${S.budgets.length ? `<div class="card flush list">${rows}</div>` : `<div class="card">${emptyBlock("◷", "Лимитов пока нет", "Поставьте лимит на категорию, например «Кафе» — 8 000 ₽ в месяц.", '<button class="btn primary sm" data-act="budget-new">Создать бюджет</button>')}</div>`}
  <div class="section-head"><h2>Цели накоплений</h2><button class="link" data-act="goal-new">Новая</button></div>
  ${goalRows(S.goals, true)}`;
}

function openBudget(category = "") {
  const used = new Set(S.budgets.map((b) => b.category));
  const existing = S.budgets.find((b) => b.category === category);
  const options = category ? [category] : S.cats.expense.filter((c) => !used.has(c));
  if (!options.length) { toast("Лимиты уже стоят на всех категориях"); return; }
  openSheet(`<h2>${category ? "Лимит на месяц" : "Новый лимит"}</h2>
    <div class="field"><label for="b-cat">Категория</label><select class="input" id="b-cat" ${category ? "disabled" : ""}>${options.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select></div>
    <div class="field"><label for="b-limit">Лимит, ₽ в месяц</label><input class="input num" id="b-limit" inputmode="decimal" placeholder="8000" value="${existing ? esc(String(existing.limit)) : ""}" /></div>
    <div class="acts-row"><button class="btn primary" id="b-save">Сохранить</button>${existing ? '<button class="btn danger" id="b-del">Убрать</button>' : '<button class="btn secondary" data-act="close-sheet">Отмена</button>'}</div>`);
  $("b-save").onclick = () => saveBudget($("b-cat").value, $("b-limit").value);
  if ($("b-del")) $("b-del").onclick = () => saveBudget($("b-cat").value, "0");
}
async function saveBudget(category, limit) {
  try {
    await post("/api/app/budgets", { category, limit });
    haptic("success"); closeSheet(); toast(limit === "0" ? "Лимит убран" : "Лимит сохранён");
    markDirty(); load(S.screen);
  } catch (e) { toast(e.message); }
}

function openGoalNew() {
  openSheet(`<h2>Новая цель</h2>
    <div class="field"><label for="g-title">Название</label><input class="input" id="g-title" maxlength="60" placeholder="Отпуск" /></div>
    <div class="field"><label for="g-target">Сумма цели, ₽</label><input class="input num" id="g-target" inputmode="decimal" placeholder="120000" /></div>
    <div class="field"><label for="g-initial">Уже накоплено, ₽</label><input class="input num" id="g-initial" inputmode="decimal" placeholder="0" /></div>
    <div class="field"><label for="g-icon">Значок</label><input class="input" id="g-icon" maxlength="4" value="🎯" /></div>
    <div class="acts-row"><button class="btn primary" id="g-save">Создать</button><button class="btn secondary" data-act="close-sheet">Отмена</button></div>`);
  $("g-save").onclick = async () => {
    try {
      await post("/api/app/goals", { title: $("g-title").value, target: $("g-target").value, initial: $("g-initial").value || 0, icon: $("g-icon").value || "🎯" });
      haptic("success"); closeSheet(); toast("Цель создана"); markDirty(); load(S.screen);
    } catch (e) { toast(e.message); }
  };
}
function openGoalTopup(id) {
  const g = S.goals.find((x) => String(x.id) === String(id));
  if (!g) return;
  openSheet(`<h2>${esc(g.icon || "🎯")} ${esc(g.title)}</h2><p class="muted num amt">Накоплено ${money(g.saved)} из ${money(g.target)}</p>
    <div class="field"><label for="g-amount">Сколько добавить, ₽</label><input class="input num" id="g-amount" inputmode="decimal" placeholder="5000" /></div>
    <div class="acts-row"><button class="btn primary" id="g-add">Пополнить</button><button class="btn secondary" data-act="close-sheet">Отмена</button></div>`);
  $("g-add").onclick = async () => {
    try {
      await post(`/api/app/goals/${g.id}/add`, { amount: $("g-amount").value });
      haptic("success"); closeSheet(); toast("Цель пополнена"); markDirty(); load(S.screen);
    } catch (e) { toast(e.message); }
  };
}
async function deleteGoal(id) {
  if (!await confirmAction("Удалить эту цель? История пополнений не сохраняется.")) return;
  try { await api(`/api/app/goals/${id}`, { method: "DELETE" }); haptic("warning"); toast("Цель удалена"); markDirty(); load(S.screen); }
  catch (e) { toast(e.message); }
}

/* ===================== СОВЕТНИК ===================== */
function mdLite(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}
function renderChat() {
  const off = S.me && S.me.ai_enabled === false;
  $("composer").setAttribute("aria-disabled", off ? "true" : "false");
  const intro = `<div class="card chat-intro"><b>✦ Советник по финансам</b><span class="muted">Отвечаю по вашим записям и считаю точно. Я помощник, а не финансовый консультант: за вас ничего не решаю и ничего не меняю.</span></div>`;
  const banner = off ? '<div class="banner">⚠️ <span>Советник сейчас выключен. Чат заработает, когда его подключат.</span></div>' : "";
  const msgs = S.chat.map((m) => m.role === "me"
    ? `<div class="bubble me">${esc(m.text)}</div>`
    : `<div class="bubble ai"${m.error ? ' style="color:var(--expense)"' : ""}>${mdLite(m.text)}</div>`).join("");
  const typing = S.aiBusy ? '<div class="bubble ai"><span class="typing"><i></i><i></i><i></i></span></div>' : "";
  $("chat").innerHTML = intro + banner + msgs + typing;
  $("ai-chips").hidden = Boolean(off);
}
async function ask(question) {
  question = question.trim();
  if (!question || S.aiBusy || (S.me && S.me.ai_enabled === false)) return;
  S.chat.push({ role: "me", text: question });
  S.aiBusy = true; $("ai-in").value = ""; renderChat();
  $("ai-bottom").scrollIntoView({ block: "end", behavior: "smooth" });
  try {
    const r = await post("/api/app/assistant", { question });
    S.chat.push({ role: "ai", text: r.answer });
  } catch (e) { S.chat.push({ role: "ai", text: e.message, error: true }); }
  S.aiBusy = false; renderChat();
  $("ai-bottom").scrollIntoView({ block: "end", behavior: "smooth" });
}

/* ===================== НАСТРОЙКИ ===================== */
async function loadSettings() {
  if (!$("sc-settings").innerHTML.trim()) $("sc-settings").innerHTML = skeleton(5);
  const [me, res] = await Promise.all([api("/api/app/me"), api("/api/app/settings")]);
  S.me = { ...S.me, ...me }; S.settings = res.settings; S.timezones = res.timezones;
  renderSettings();
}
function renderSettings() {
  const st = S.settings;
  $("sc-settings").innerHTML = `
  <div class="topbar"><div class="title"><span class="eyebrow">Профиль</span><h1>Настройки</h1></div></div>
  <div class="card"><b>${esc(S.me.display_name || "Пользователь")}</b><div class="muted">${S.me.user_id ? "Telegram ID · " + esc(S.me.user_id) : "Личный финансовый профиль"}</div></div>
  <div class="section-head"><h2>Оформление</h2></div>
  <div class="segmented" id="theme-seg">${[["system", "Как в Telegram"], ["light", "Светлая"], ["dark", "Тёмная"]].map(([k, n]) => `<button data-theme="${k}" class="${st.theme === k ? "on" : ""}">${n}</button>`).join("")}</div>
  <div class="section-head"><h2>Время и уведомления</h2></div>
  <div class="card flush">
    <div class="kv"><label for="tz">Часовой пояс</label><select class="input" id="tz" style="width:auto;min-height:40px">${S.timezones.map((z) => `<option value="${esc(z)}"${z === st.timezone ? " selected" : ""}>${esc(z)}</option>`).join("")}</select></div>
    <div class="kv"><label for="sw-budget">Предупреждать о лимитах</label><input class="switch" type="checkbox" id="sw-budget" ${st.budget_notifications ? "checked" : ""} /></div>
    <div class="kv"><label for="sw-weekly">Сводка по понедельникам</label><input class="switch" type="checkbox" id="sw-weekly" ${st.weekly_summary ? "checked" : ""} /></div>
  </div>
  <div class="section-head"><h2>Данные</h2></div>
  <div class="card flush">
    <button class="row" data-act="export"><span class="cat-ico" style="--c:var(--accent)">📤</span><span class="main"><b>Скачать в Excel</b><span>Все операции, бюджеты и цели</span></span></button>
    <button class="row" data-act="wipe"><span class="cat-ico" style="--c:var(--expense)">🗑</span><span class="main"><b class="neg">Удалить все данные</b><span>Операции, бюджеты, цели. Это нельзя отменить</span></span></button>
  </div>`;
}
async function saveSettings(patch = {}) {
  const next = { ...S.settings, ...patch };
  try {
    await post("/api/app/settings", { theme: next.theme, timezone: next.timezone, budget_notifications: Boolean(next.budget_notifications), weekly_summary: Boolean(next.weekly_summary) });
    S.settings = next;
    if (patch.theme) applyTheme(next.theme);
    haptic("success"); toast("Сохранено");
    if (patch.timezone) { markDirty(); S.dirty.settings = false; }
  } catch (e) { toast(e.message); renderSettings(); }
}
async function exportWorkbook() {
  try {
    const response = await fetch("/api/app/export", { headers });
    if (!response.ok) throw new Error("Не удалось подготовить файл");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url; a.download = "tracker-finance.xlsx"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Файл подготовлен");
  } catch (e) { toast(e.message); }
}
async function wipeData() {
  if (!await confirmAction("Удалить все операции, бюджеты, цели и правила? Это нельзя отменить.")) return;
  if (!await confirmAction("Точно удалить всё? Вернуть данные не получится.")) return;
  try { await api("/api/app/data", { method: "DELETE" }); haptic("warning"); toast("Данные удалены"); S.monthStats = null; markDirty(); show("home", { force: true }); }
  catch (e) { toast(e.message); }
}

/* ===================== События ===================== */
let suppressClick = false, swipe = null;
function closeSwiped(except) {
  document.querySelectorAll(".swipe-wrap .row.swiped").forEach((r) => { if (r !== except) r.classList.remove("swiped"); });
}
document.addEventListener("pointerdown", (e) => {
  const row = e.target.closest(".swipe-wrap .row");
  closeSwiped(row);
  swipe = row ? { row, x: e.clientX, y: e.clientY, moved: false } : null;
});
document.addEventListener("pointermove", (e) => {
  if (!swipe) return;
  const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
  if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) swipe.moved = true;
});
document.addEventListener("pointerup", (e) => {
  if (!swipe) return;
  if (swipe.moved) {
    swipe.row.classList.toggle("swiped", e.clientX - swipe.x < -30);
    suppressClick = true; setTimeout(() => { suppressClick = false; }, 60);
  }
  swipe = null;
});
document.addEventListener("pointercancel", () => { swipe = null; });

const ACTIONS = {
  "add-exp": () => openAdd("expense"),
  "add-inc": () => openAdd("income"),
  plans: () => show("plans"), ai: () => show("ai"), history: () => show("history"), settings: () => show("settings"),
  eye: () => { S.hide = !S.hide; store("tf.hide", S.hide ? "1" : "0"); applyHide(); if (S.screen === "home" && S.monthStats) renderHome(); },
  "tip-hide": () => { S.tipHidden = true; renderHome(); },
  "pick-category": () => { if (S.hCat) { S.hCat = ""; loadHistory(true).catch((e) => toast(e.message)); } else pickCategoryFilter(); },
  more: () => loadHistory(false).catch((e) => toast(e.message)),
  "close-sheet": closeSheet,
  "goal-new": openGoalNew, "budget-new": () => openBudget(),
  "edit-save": saveEdit,
  "edit-del": async () => { if (await confirmAction("Удалить эту операцию? Её можно вернуть в течение нескольких секунд.")) deleteTx(edit.id); },
  export: exportWorkbook, wipe: wipeData,
  retry: () => show(S.screen, { force: true }),
};

document.addEventListener("click", async (e) => {
  if (suppressClick) { e.preventDefault(); return; }
  if (e.target === $("overlay")) { closeSheet(); return; }
  const el = e.target.closest("button, .row, label.chip");
  if (!el) return;
  const d = el.dataset;

  if (d.tab) { if (d.tab === "add") openAdd("expense"); else { if (S.sheetOpen) closeSheet(); show(d.tab); } return; }
  if (d.act && ACTIONS[d.act]) { ACTIONS[d.act](); return; }
  if (d.n) return numpadPress(d.n);
  if (d.k) { add.kind = d.k; add.cat = S.cats[add.kind][0] || ""; syncAdd(true); return; }
  if (d.c && el.closest("#add-cats")) { add.cat = d.c; haptic("tap"); syncAdd(); return; }
  if (d.addAct === "note") { const n = $("a-note"); n.hidden = !n.hidden; if (!n.hidden) n.focus(); return; }
  if (d.addAct === "words") { openQuickText(); return; }
  if (d.ek) { edit.kind = d.ek; syncEdit(); return; }
  if (d.ec) { edit.cat = d.ec; syncEdit(); return; }
  if (d.p) return setHomePeriod(d.p);
  if (d.sp) { S.statsPeriod = d.sp; load("stats"); return; }
  if (d.sk) { S.statsKind = d.sk; load("stats"); return; }
  if (d.kind && el.closest("#history-chips")) {
    S.hKind = d.kind; S.hCat = ""; S.hQ = ""; $("history-search").value = "";
    document.querySelectorAll("#history-chips [data-kind]").forEach((b) => b.classList.toggle("on", b === el));
    loadHistory(true).catch((err) => toast(err.message)); return;
  }
  if (d.catFilter !== undefined) { S.hCat = d.catFilter; closeSheet(); loadHistory(true).catch((err) => toast(err.message)); return; }
  if (d.ask) return ask(d.ask);
  if (d.theme) { document.querySelectorAll("#theme-seg button").forEach((b) => b.classList.toggle("on", b === el)); saveSettings({ theme: d.theme }); return; }
  if (d.del) { deleteTx(d.del); return; }
  if (d.tx) { if (el.classList.contains("swiped")) { el.classList.remove("swiped"); return; } openEdit(d.tx); return; }
  if (d.budget) { openBudget(d.budget); return; }
  if (d.goalAdd) { openGoalTopup(d.goalAdd); return; }
  if (d.goalDel) { deleteGoal(d.goalDel); return; }
  if (d.undo) {
    try { await api(`/api/app/transactions/${d.undo}/restore`, { method: "POST" }); toast("Удаление отменено"); markDirty(); load(S.screen); }
    catch (err) { toast(err.message); }
    return;
  }
  if (el.id === "add-save") return saveAdd();
  if (el.id === "q-go") return runQuickText();
  if (el.id === "q-ok") return confirmQuick();
});

document.addEventListener("input", (e) => {
  if (e.target.id === "a-dt") { add.dt = e.target.value || add.dt; add.dtTouched = true; syncAdd(); }
});
document.addEventListener("change", (e) => {
  if (e.target.id === "tz") saveSettings({ timezone: e.target.value });
  if (e.target.id === "sw-budget") saveSettings({ budget_notifications: e.target.checked });
  if (e.target.id === "sw-weekly") saveSettings({ weekly_summary: e.target.checked });
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && S.sheetOpen) closeSheet();
  if (e.key === "Enter" && e.target.id === "q-text") runQuickText();
});

let searchTimer;
$("history-search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  S.hQ = e.target.value.trim();
  searchTimer = setTimeout(() => loadHistory(true).catch((err) => toast(err.message)), 250);
});
$("composer").addEventListener("submit", (e) => { e.preventDefault(); ask($("ai-in").value); });

function applyHide() { $("app").classList.toggle("blur-amounts", S.hide); }

function handleBack() {
  if (S.sheetOpen) closeSheet();
  else if (S.screen === "plans" || S.screen === "settings") show("home");
}

/* ===================== Запуск ===================== */
async function boot() {
  const [me, res] = await Promise.all([api("/api/app/me"), api("/api/app/settings")]);
  S.me = me; S.cats = me.categories; S.settings = res.settings; S.timezones = res.timezones;
  applyTheme(res.settings.theme);
  applyHide();
  if (tg) {
    if (tg.BackButton) tgTry(() => tg.BackButton.onClick(handleBack));
    if (tg.SettingsButton) tgTry(() => tg.SettingsButton.onClick(() => show("settings")));
    if (useTgMain) tgTry(() => tg.MainButton.onClick(() => { if (S.mainAction) S.mainAction(); }));
    tgTry(() => tg.onEvent("themeChanged", applyScheme));
  }
  markDirty();
  show("home", { force: true });
}

$("dev-enter").onclick = async () => {
  headers.Authorization = `Bearer ${$("dev-token").value.trim()}`;
  $("login-err").textContent = "";
  try { await boot(); } catch (e) { $("login-err").textContent = e.message; }
};

applyScheme();
if (inTelegram) {
  boot().catch((e) => { $("login").classList.add("on"); $("login-err").textContent = e.message; });
} else {
  $("login").classList.add("on");
}
