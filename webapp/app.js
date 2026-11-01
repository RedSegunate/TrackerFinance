const tg = window.Telegram && window.Telegram.WebApp;
const inTelegram = Boolean(tg && tg.initData);
if (tg) {
  tg.ready();
  tg.expand();
  if (inTelegram) tg.setHeaderColor("secondary_bg_color");
}

const headers = { "Content-Type": "application/json" };
if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
const state = {
  categories: { expense: [], income: [] },
  user: {},
  settings: {},
  historyKind: "all",
  historyCategory: "",
  historyQuery: "",
  transactionMap: new Map(),
  historyItems: [],
  historyOffset: 0,
  quickPreviewItems: [],
  addKind: "expense",
  selectedCategory: "",
  homePeriod: "month",
  analyticsPeriod: "month",
  balanceVisible: true,
  activeScreen: "home",
  toastTimer: null,
};

const $ = (id) => document.getElementById(id);
const categoryIcons = {
  "Продукты": "🛒", "Кафе и рестораны": "☕", "Транспорт": "🚕", "Авто": "🚘",
  "Жильё": "⌂", "Связь и интернет": "⌁", "Здоровье": "♥", "Одежда": "◈",
  "Красота": "✦", "Развлечения": "♫", "Подписки": "▣", "Образование": "▤",
  "Семья и дети": "♡", "Подарки": "✿", "Путешествия": "✈", "Бизнес-расходы": "▰",
  "Зарплата": "▣", "Подработка": "⌘", "Бизнес": "▰", "Подарок": "✿", "Другое": "◦",
};
const chartColors = ["#65d8bd", "#77a9ff", "#f4b65f", "#fb7185", "#9b8cff", "#61c1da", "#a7c86d"];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function money(amount) {
  const value = Number(amount) || 0;
  const rounded = Math.abs(value - Math.round(value)) > 0.004 ? value.toFixed(2) : Math.round(value);
  return `${String(rounded).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} ₽`;
}

function localInputDate(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Ошибка запроса (${response.status})`);
  }
  return data;
}

function toast(message, undoId = null) {
  const el = $("toast");
  clearTimeout(state.toastTimer);
  el.replaceChildren(document.createTextNode(message));
  if (undoId !== null) {
    const button = document.createElement("button");
    button.className = "link-button";
    button.dataset.undo = String(undoId);
    button.textContent = "Отменить";
    button.style.marginLeft = "12px";
    el.append(button);
  }
  el.style.display = "block";
  state.toastTimer = setTimeout(() => { el.style.display = "none"; }, undoId === null ? 2800 : 7000);
}

function show(id) {
  state.activeScreen = id;
  document.querySelectorAll("#app > .screen").forEach((screen) => {
    screen.classList.toggle("on", screen.id === id);
  });
  document.querySelectorAll(".nav button").forEach((button) => {
    button.classList.toggle("on", button.dataset.s === id);
  });
  if (inTelegram && tg.BackButton) {
    if (id === "home") tg.BackButton.hide();
    else tg.BackButton.show();
  }
  if (inTelegram && tg.MainButton) {
    if (id === "add") {
      tg.MainButton.setText("Сохранить операцию");
      tg.MainButton.show();
    } else {
      tg.MainButton.hide();
    }
  }
  const loaders = {
    home: loadHome,
    analytics: () => loadAnalytics(state.analyticsPeriod),
    history: loadHistory,
    budgets: loadBudgets,
    goals: loadGoals,
    profile: loadProfile,
  };
  if (loaders[id]) loaders[id]().catch((error) => toast(error.message));
}

function setTheme(theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
  if (inTelegram && tg.setHeaderColor) {
    tg.setHeaderColor(theme === "light" ? "#f3f6f5" : theme === "dark" ? "#101519" : "secondary_bg_color");
  }
}

function haptic(type = "success") {
  if (inTelegram && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(type);
}

function fillSelect(select, options, selected = "") {
  select.innerHTML = options.map((value) =>
    `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(value)}</option>`
  ).join("");
}

function renderCategoryGrid() {
  const list = state.categories[state.addKind] || [];
  if (!list.includes(state.selectedCategory)) state.selectedCategory = list[0] || "";
  $("category-grid").innerHTML = list.map((category) => `
    <button class="category-choice${category === state.selectedCategory ? " on" : ""}" type="button" data-category="${escapeHtml(category)}">
      <span>${categoryIcons[category] || "◦"}</span><span>${escapeHtml(category)}</span>
    </button>`).join("");
}

function setAddKind(kind) {
  state.addKind = kind;
  document.querySelectorAll("#kind button").forEach((button) => {
    button.classList.toggle("on", button.dataset.k === kind);
  });
  renderCategoryGrid();
}

function renderTransaction(item) {
  const sign = item.kind === "expense" ? "−" : "+";
  const typeClass = item.kind === "expense" ? "negative" : "positive";
  return `
    <button class="transaction-row" type="button" data-tx="${item.id}">
      <span class="category-dot" style="background:${item.kind === "expense" ? "var(--bad)" : "var(--good)"}"></span>
      <span class="row-main"><strong>${categoryIcons[item.category] || "◦"} ${escapeHtml(item.category)}</strong>
      <span class="muted">${escapeHtml(item.note || "Без описания")} · ${escapeHtml(item.when)}</span></span>
      <span class="row-value ${typeClass}">${sign}${escapeHtml(item.amount_text)}</span>
    </button>`;
}

function emptyState(icon, text, action = "") {
  return `<div class="empty"><div class="empty-icon">${icon}</div><p class="muted">${escapeHtml(text)}</p>${action}</div>`;
}

function dateGroupLabel(date) {
  const parsed = new Date(`${date}T00:00:00`);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (parsed.toDateString() === today.toDateString()) return "Сегодня";
  if (parsed.toDateString() === yesterday.toDateString()) return "Вчера";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(parsed);
}

function showSkeleton(container, count = 3) {
  container.innerHTML = Array.from({ length: count }, () => '<div class="skeleton"></div>').join("");
}

function renderTransactions(container, items, compact = false) {
  for (const item of items) state.transactionMap.set(String(item.id), item);
  if (!items.length) {
    container.innerHTML = emptyState("◌", "Здесь пока нет операций.", '<button class="link-button" data-open="add">Добавить операцию</button>');
    return;
  }
  if (compact) {
    container.innerHTML = items.slice(0, 3).map(renderTransaction).join("");
    return;
  }
  let previousDate = "";
  const groups = [];
  for (const item of items) {
    const date = String(item.datetime || "").slice(0, 10);
    if (date !== previousDate) {
      groups.push(`<div class="history-date">${escapeHtml(date ? dateGroupLabel(date) : "Дата не указана")}</div>`);
      previousDate = date;
    }
    groups.push(renderTransaction(item));
  }
  container.innerHTML = groups.join("");
}

function renderBudgets(items, container, compact = false) {
  const shown = compact ? items.slice(0, 2) : items;
  if (!shown.length) {
    container.innerHTML = emptyState("◷", "Пока нет установленных лимитов.", '<button class="link-button" data-open="budgets">Создать первый бюджет</button>');
    return;
  }
  container.innerHTML = shown.map((budget) => {
    const pct = Math.max(0, Number(budget.pct) || 0);
    const color = pct >= 100 ? "var(--bad)" : pct >= 90 ? "#f18a56" : pct >= 70 ? "var(--warn)" : "var(--btn)";
    return `<div class="budget-row">
      <div class="goal-meta"><strong>${categoryIcons[budget.category] || "◦"} ${escapeHtml(budget.category)}</strong><span class="muted">${escapeHtml(budget.spent_text)} / ${escapeHtml(budget.limit_text)}</span></div>
      <div class="progress"><i style="width:${Math.min(100, pct)}%;background:${color}"></i></div>
      <div class="muted" style="margin-top:5px">${pct}% использовано</div>
    </div>`;
  }).join("");
}

function renderGoals(items, container, compact = false) {
  const shown = compact ? items.slice(0, 2) : items;
  if (!shown.length) {
    container.innerHTML = emptyState("◎", "Большие цели начинаются с маленьких накоплений.", '<button class="link-button" data-open="goals">Создать первую цель</button>');
    return;
  }
  container.innerHTML = shown.map((goal) => {
    const remaining = Math.max(0, goal.target - goal.saved);
    return `<div class="goal-row" data-goal="${goal.id}">
      <div class="goal-meta"><strong>${escapeHtml(goal.icon || "🎯")} ${escapeHtml(goal.title)}</strong><span class="muted">${goal.pct}%</span></div>
      <div class="muted" style="margin-bottom:7px">${money(goal.saved)} / ${money(goal.target)} · осталось ${money(remaining)}</div>
      <div class="progress"><i style="width:${goal.pct}%"></i></div>
      ${compact ? "" : `<div class="goal-actions"><input data-goal-amount type="number" min="0.01" step="100" inputmode="decimal" placeholder="Пополнить, ₽" aria-label="Сумма пополнения" /><button class="secondary" data-goal-add>Пополнить</button><button class="danger" data-goal-delete aria-label="Удалить цель">Удалить</button></div>`}
    </div>`;
  }).join("");
}

function setHomeStats(data) {
  $("home-period-income").textContent = money(data.income);
  $("home-period-expense").textContent = money(data.expense);
  const delta = $("home-period-delta");
  delta.textContent = `${data.balance > 0 ? "+" : data.balance < 0 ? "−" : ""}${money(Math.abs(data.balance))}`;
  delta.className = data.balance >= 0 ? "positive" : "negative";
}

async function loadHome() {
  if (!$("home-transactions").innerHTML.trim()) showSkeleton($("home-transactions"), 2);
  if (!$("home-budgets").innerHTML.trim()) showSkeleton($("home-budgets"), 1);
  if (!$("home-goals").innerHTML.trim()) showSkeleton($("home-goals"), 1);
  const [month, period, transactions, budgets, goals] = await Promise.all([
    api("/api/app/stats?period=month"),
    api(`/api/app/stats?period=${state.homePeriod}`),
    api("/api/app/transactions"),
    api("/api/app/budgets"),
    api("/api/app/goals"),
  ]);
  const balance = $("balance");
  balance.textContent = state.balanceVisible ? money(month.overall_balance) : "•••••• ₽";
  $("home-income").textContent = `+${money(month.income)}`;
  $("home-expense").textContent = `−${money(month.expense)}`;
  setHomeStats(period);
  renderTransactions($("home-transactions"), transactions.items, true);
  renderBudgets(budgets.items, $("home-budgets"), true);
  renderGoals(goals.items, $("home-goals"), true);
}

function categoryColor(index) {
  return chartColors[index % chartColors.length];
}

function renderAnalyticsCategories(categories, total) {
  const container = $("analytics-categories");
  if (!categories.length) {
    container.innerHTML = emptyState("◌", "Недостаточно данных для разбивки по категориям.");
    return;
  }
  let angle = 0;
  const stops = categories.map((item, index) => {
    const start = angle;
    angle += Math.max(0, Number(item.share) || 0) * 3.6;
    return `${categoryColor(index)} ${start}deg ${angle}deg`;
  });
  const rows = categories.map((item, index) => `
    <button class="category-row" type="button" data-category-filter="${escapeHtml(item.category)}">
      <span class="category-dot" style="background:${categoryColor(index)}"></span>
      <span class="row-main"><strong>${escapeHtml(item.category)}</strong><span class="muted">${Math.round(item.share)}% расходов</span></span>
      <span class="row-value">${money(item.amount)}</span>
    </button>`).join("");
  container.innerHTML = `
    <div class="donut-wrap"><div class="donut" style="background:conic-gradient(${stops.join(",")})"><div class="donut-hole"><span class="muted">Расходы</span><strong>${money(total)}</strong></div></div></div>
    <div>${rows}</div>`;
}

function drawChart(series) {
  const canvas = $("spend-chart");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const pad = { left: 36, right: 8, top: 14, bottom: 28 };
  const values = series.map((item) => Number(item.amount) || 0);
  const maximum = Math.max(1, ...values);
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const css = getComputedStyle(document.documentElement);
  const grid = css.getPropertyValue("--line").trim();
  const muted = css.getPropertyValue("--hint").trim();
  const accent = css.getPropertyValue("--btn").trim();
  ctx.font = "11px DM Sans, sans-serif";
  ctx.fillStyle = muted;
  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  for (let line = 0; line < 4; line += 1) {
    const y = pad.top + (plotHeight * line) / 3;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(money(maximum * (1 - line / 3)).replace(" ₽", ""), 0, y + 4);
  }
  if (!values.length) return;
  const points = values.map((value, index) => ({
    x: pad.left + (values.length < 2 ? plotWidth / 2 : (plotWidth * index) / (values.length - 1)),
    y: pad.top + plotHeight - (value / maximum) * plotHeight,
  }));
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.stroke();
  ctx.fillStyle = accent;
  points.forEach((point) => { ctx.beginPath(); ctx.arc(point.x, point.y, 2.5, 0, Math.PI * 2); ctx.fill(); });
  canvas.onclick = () => {
    const pointerX = canvas._pointerX;
    if (pointerX === undefined) return;
    const nearest = points.reduce((best, point, index) =>
      Math.abs(point.x - pointerX) < Math.abs(points[best].x - pointerX) ? index : best, 0);
    toast(`${series[nearest].label}: ${money(series[nearest].amount)}`);
  };
  canvas.onpointerdown = (event) => {
    canvas._pointerX = event.clientX - canvas.getBoundingClientRect().left;
  };
  canvas.onpointermove = (event) => {
    const pointerX = event.clientX - canvas.getBoundingClientRect().left;
    canvas._pointerX = pointerX;
    const nearest = points.reduce((best, point, index) =>
      Math.abs(point.x - pointerX) < Math.abs(points[best].x - pointerX) ? index : best, 0);
    canvas.title = `${series[nearest].label}: ${money(series[nearest].amount)}`;
  };
  const step = Math.max(1, Math.ceil(series.length / 6));
  series.forEach((item, index) => {
    if (index % step && index !== series.length - 1) return;
    const point = points[index];
    ctx.fillStyle = muted;
    ctx.textAlign = "center";
    ctx.fillText(item.label, point.x, height - 6);
  });
  ctx.textAlign = "start";
}

async function loadAnalytics(period = state.analyticsPeriod) {
  state.analyticsPeriod = period;
  if (!$("analytics-categories").innerHTML.trim()) showSkeleton($("analytics-categories"), 3);
  if (!$("insights").innerHTML.trim()) showSkeleton($("insights"), 2);
  const data = await api(`/api/app/stats?period=${period}`);
  $("analytics-income").textContent = money(data.income);
  $("analytics-expense").textContent = money(data.expense);
  const delta = $("analytics-delta");
  delta.textContent = `${data.balance > 0 ? "+" : data.balance < 0 ? "−" : ""}${money(Math.abs(data.balance))}`;
  delta.className = data.balance >= 0 ? "positive" : "negative";
  renderAnalyticsCategories(data.categories, data.expense);
  $("insights").innerHTML = data.insights.length
    ? data.insights.map((insight) => `<div class="insight">${escapeHtml(insight)}</div>`).join("")
    : emptyState("💡", "Пока недостаточно данных для наблюдений.");
  requestAnimationFrame(() => drawChart(data.series));
}

async function loadHistory(reset = true) {
  if (reset) {
    state.historyItems = [];
    state.historyOffset = 0;
  }
  const params = new URLSearchParams({ kind: state.historyKind });
  if (state.historyQuery) params.set("q", state.historyQuery);
  if (state.historyCategory) params.set("category", state.historyCategory);
  params.set("offset", String(state.historyOffset));
  if (reset) showSkeleton($("tx-list"), 4);
  const data = await api(`/api/app/transactions?${params}`);
  state.historyItems.push(...data.items);
  state.historyOffset = data.next_offset;
  renderTransactions($("tx-list"), state.historyItems);
  if (data.has_more) {
    const more = document.createElement("button");
    more.className = "secondary";
    more.dataset.historyMore = "true";
    more.textContent = "Показать ещё";
    more.style.width = "100%";
    $("tx-list").append(more);
  }
  if (state.historyCategory) {
    $("history-search").placeholder = `Категория: ${state.historyCategory}`;
  } else {
    $("history-search").placeholder = "Название, категория или сумма";
  }
}

async function loadBudgets() {
  const data = await api("/api/app/budgets");
  renderBudgets(data.items, $("budget-list"));
}

async function loadGoals() {
  const data = await api("/api/app/goals");
  const saved = data.items.reduce((sum, goal) => sum + goal.saved, 0);
  const target = data.items.reduce((sum, goal) => sum + goal.target, 0);
  $("goals-saved").textContent = money(saved);
  $("goals-summary").textContent = data.items.length
    ? `${money(saved)} из ${money(target)} · активных целей: ${data.items.length}`
    : "Цели пока не добавлены";
  renderGoals(data.items, $("goal-list"));
}

async function loadProfile() {
  const [me, result] = await Promise.all([api("/api/app/me"), api("/api/app/settings")]);
  $("profile-name").textContent = me.display_name || "Пользователь";
  $("profile-id").textContent = me.user_id ? `Telegram ID · ${me.user_id}` : "Личный финансовый профиль";
  fillSelect($("timezone-setting"), result.timezones, result.settings.timezone);
  $("theme-setting").value = result.settings.theme;
  $("budget-alert-setting").checked = Boolean(result.settings.budget_notifications);
  $("weekly-setting").checked = Boolean(result.settings.weekly_summary);
  state.settings = result.settings;
}

function setHistoryFilter(kind, category = "") {
  state.historyKind = kind;
  state.historyCategory = category;
  state.historyQuery = "";
  $("history-search").value = "";
  document.querySelectorAll("#history-filters button").forEach((button) => {
    button.classList.toggle("on", button.dataset.kind === kind);
  });
  show("history");
}

function openTransaction(id) {
  const item = state.transactionMap.get(String(id));
  if (!item) return;
  const categories = state.categories[item.kind] || [];
  const options = categories.map((category) =>
    `<option value="${escapeHtml(category)}"${category === item.category ? " selected" : ""}>${escapeHtml(category)}</option>`
  ).join("");
  $("tx-sheet").innerHTML = `
    <div class="sheet-head"><h2>Операция #${item.id}</h2><button class="icon-button" data-close aria-label="Закрыть">×</button></div>
    <div class="periods" id="edit-kind"><button data-k="expense" class="${item.kind === "expense" ? "on" : ""}">− Расход</button><button data-k="income" class="${item.kind === "income" ? "on" : ""}">＋ Доход</button></div>
    <div class="field"><label for="edit-amount">Сумма, ₽</label><input id="edit-amount" type="number" min="0.01" step="0.01" value="${item.amount}" /></div>
    <div class="field"><label for="edit-category">Категория</label><select id="edit-category">${options}</select></div>
    <div class="field"><label for="edit-note">Описание</label><input id="edit-note" maxlength="100" value="${escapeHtml(item.note)}" /></div>
    <div class="field"><label for="edit-date">Дата и время</label><input id="edit-date" type="datetime-local" value="${escapeHtml(localInputDate(new Date(item.datetime)))}" /></div>
    <div class="sheet-actions"><button class="secondary" data-save-tx>Сохранить</button><button class="danger" data-delete-tx>Удалить</button></div>
    <p class="muted" style="margin-top:10px">Изменения затронут только эту операцию.</p>`;
  $("tx-dialog").showModal();
  $("edit-kind").onclick = (event) => {
    const button = event.target.closest("button[data-k]");
    if (!button) return;
    item.kind = button.dataset.k;
    $("edit-kind").querySelectorAll("button").forEach((choice) => choice.classList.toggle("on", choice === button));
    fillSelect($("edit-category"), state.categories[item.kind], state.categories[item.kind][0]);
  };
  $("tx-sheet").onclick = async (event) => {
    if (event.target.closest("[data-close]")) $("tx-dialog").close();
    if (event.target.closest("[data-save-tx]")) {
      try {
        await api(`/api/app/transactions/${item.id}`, { method: "PATCH", body: JSON.stringify({
          kind: $("edit-kind").querySelector("button.on").dataset.k,
          amount: $("edit-amount").value,
          category: $("edit-category").value,
          note: $("edit-note").value,
          datetime: new Date($("edit-date").value).toISOString(),
        })});
        $("tx-dialog").close();
        toast("Операция обновлена");
        await loadHistory(); await loadHome();
      } catch (error) { toast(error.message); }
    }
    if (event.target.closest("[data-delete-tx]")) {
      if (!await confirmAction("Удалить эту операцию? Её можно будет восстановить в течение нескольких секунд.")) return;
      try {
        const result = await api(`/api/app/transactions/${item.id}`, { method: "DELETE" });
        $("tx-dialog").close();
        toast("Операция удалена", result.undo_id);
        await loadHistory(); await loadHome();
      } catch (error) { toast(error.message); }
    }
  };
}

function confirmAction(message) {
  if (inTelegram && tg.showConfirm) return new Promise((resolve) => tg.showConfirm(message, resolve));
  return Promise.resolve(window.confirm(message));
}

async function saveOperation() {
  $("add-err").textContent = "";
  try {
    await api("/api/app/add", { method: "POST", body: JSON.stringify({
      kind: state.addKind,
      amount: $("amount").value,
      category: state.selectedCategory,
      note: $("note").value,
      datetime: new Date($("transaction-date").value).toISOString(),
    })});
    $("amount").value = "";
    $("note").value = "";
    $("transaction-date").value = localInputDate();
    haptic("success");
    toast("Операция добавлена");
    show("home");
  } catch (error) {
    $("add-err").textContent = error.message;
  }
}

function renderQuickPreview(items) {
  state.quickPreviewItems = items;
  const preview = $("quick-preview");
  preview.innerHTML = `
    <div class="goal-row">
      <p class="muted">Проверьте распознанные операции и выберите категорию для каждой траты, которую бот не смог определить.</p>
      ${items.map((item, index) => {
        const categories = state.categories[item.kind] || [];
        return `<div class="field">
          <label>${item.kind === "income" ? "Доход" : "Расход"} · ${money(item.amount)} · ${escapeHtml(item.note || "Без описания")}</label>
          <select data-preview-category="${index}">${categories.map((category) =>
            `<option value="${escapeHtml(category)}"${category === item.category ? " selected" : ""}>${escapeHtml(category)}</option>`
          ).join("")}</select>
        </div>`;
      }).join("")}
      <button class="primary" type="button" data-confirm-quick>Подтвердить и сохранить</button>
    </div>`;
}

async function confirmQuickItems() {
  const items = state.quickPreviewItems.map((item, index) => ({
    ...item,
    uncertain: item.category === "Другое",
    category: $("quick-preview").querySelector(`[data-preview-category="${index}"]`).value,
  }));
  const result = await api("/api/app/add", { method: "POST", body: JSON.stringify({ items }) });
  state.quickPreviewItems = [];
  $("quick-preview").replaceChildren();
  $("quick").value = "";
  haptic("success");
  toast(result.reply.split("\n")[0]);
  await loadHome();
}

async function saveQuickText() {
  const text = $("quick").value.trim();
  if (!text) return;
  try {
    const result = await api("/api/app/add", { method: "POST", body: JSON.stringify({ text }) });
    if (!result.confirmed) {
      renderQuickPreview(result.items);
      return;
    }
    $("quick").value = "";
    $("quick-preview").replaceChildren();
    haptic("success");
    toast(result.reply.split("\n")[0]);
    await loadHome();
  } catch (error) { toast(error.message); }
}

async function saveSettings() {
  $("settings-err").textContent = "";
  const theme = $("theme-setting").value;
  try {
    await api("/api/app/settings", { method: "POST", body: JSON.stringify({
      theme,
      timezone: $("timezone-setting").value,
      budget_notifications: $("budget-alert-setting").checked,
      weekly_summary: $("weekly-setting").checked,
    })});
    state.settings = { theme, timezone: $("timezone-setting").value };
    setTheme(theme);
    haptic("success");
    toast("Настройки сохранены");
  } catch (error) { $("settings-err").textContent = error.message; }
}

async function exportWorkbook() {
  try {
    const response = await fetch("/api/app/export", { headers });
    if (!response.ok) throw new Error("Не удалось подготовить экспорт");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "tracker-finance.xlsx";
    link.click();
    URL.revokeObjectURL(url);
    toast("Экспорт подготовлен");
  } catch (error) { toast(error.message); }
}

async function deleteAllData() {
  if (!await confirmAction("Удалить все операции, бюджеты, цели и правила? Это действие нельзя отменить.")) return;
  try {
    await api("/api/app/data", { method: "DELETE" });
    toast("Финансовые данные удалены");
    await loadHome();
    await loadGoals();
    await loadBudgets();
  } catch (error) { toast(error.message); }
}

async function boot() {
  const [me, settingsResult] = await Promise.all([api("/api/app/me"), api("/api/app/settings")]);
  state.user = me;
  state.categories = me.categories;
  state.settings = settingsResult.settings;
  $("welcome-name").textContent = me.display_name || "Твои финансы";
  const hour = new Date().getHours();
  $("greeting").textContent = hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";
  $("profile-name").textContent = me.display_name || "Пользователь";
  $("profile-id").textContent = me.user_id ? `Telegram ID · ${me.user_id}` : "Личный финансовый профиль";
  fillSelect($("budget-cat"), state.categories.expense);
  fillSelect($("timezone-setting"), settingsResult.timezones, settingsResult.settings.timezone);
  $("theme-setting").value = settingsResult.settings.theme;
  $("budget-alert-setting").checked = Boolean(settingsResult.settings.budget_notifications);
  $("weekly-setting").checked = Boolean(settingsResult.settings.weekly_summary);
  setTheme(settingsResult.settings.theme);
  setAddKind("expense");
  $("transaction-date").value = localInputDate();
  $("login").classList.remove("on");
  $("app").classList.add("on");
  if (inTelegram && tg.MainButton) $("add-form").hidden = true;
  await loadHome();
}

document.querySelector(".nav").onclick = (event) => {
  const button = event.target.closest("button[data-s]");
  if (button) show(button.dataset.s);
};
document.querySelector("#app").onclick = (event) => {
  const openButton = event.target.closest("[data-open]");
  if (openButton) show(openButton.dataset.open);
  const addButton = event.target.closest("[data-add-kind]");
  if (addButton) { setAddKind(addButton.dataset.addKind); show("add"); }
  const categoryButton = event.target.closest("[data-category]");
  if (categoryButton && categoryButton.closest("#category-grid")) {
    state.selectedCategory = categoryButton.dataset.category;
    renderCategoryGrid();
  }
  const transaction = event.target.closest("[data-tx]");
  if (transaction) openTransaction(transaction.dataset.tx);
  const categoryFilter = event.target.closest("[data-category-filter]");
  if (categoryFilter) setHistoryFilter("all", categoryFilter.dataset.categoryFilter);
};

[ ["home-periods", "home"], ["analytics-periods", "analytics"] ].forEach(([id, screen]) => {
  $(id).onclick = (event) => {
    const button = event.target.closest("button[data-p]");
    if (!button) return;
    $(id).querySelectorAll("button").forEach((item) => item.classList.toggle("on", item === button));
    if (screen === "home") {
      state.homePeriod = button.dataset.p;
      api(`/api/app/stats?period=${state.homePeriod}`).then(setHomeStats).catch((error) => toast(error.message));
    } else {
      loadAnalytics(button.dataset.p).catch((error) => toast(error.message));
    }
  };
});

$("kind").onclick = (event) => {
  const button = event.target.closest("button[data-k]");
  if (button) setAddKind(button.dataset.k);
};
$("add-form").onclick = saveOperation;
$("add-quick").onclick = saveQuickText;
$("quick-preview").onclick = (event) => {
  if (event.target.closest("[data-confirm-quick]")) confirmQuickItems().catch((error) => toast(error.message));
};
if (inTelegram && tg.MainButton) tg.MainButton.onClick(saveOperation);
if (inTelegram && tg.BackButton) tg.BackButton.onClick(() => show("home"));

$("history-filters").onclick = (event) => {
  const button = event.target.closest("button[data-kind]");
  if (!button) return;
  state.historyKind = button.dataset.kind;
  state.historyCategory = "";
  state.historyQuery = "";
  state.historyOffset = 0;
  $("history-search").value = "";
  $("history-filters").querySelectorAll("button").forEach((item) => item.classList.toggle("on", item === button));
  loadHistory().catch((error) => toast(error.message));
};
let searchTimer;
$("history-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  state.historyQuery = $("history-search").value.trim();
  searchTimer = setTimeout(() => loadHistory(true).catch((error) => toast(error.message)), 250);
});
$("tx-list").onclick = (event) => {
  if (event.target.closest("[data-history-more]")) loadHistory(false).catch((error) => toast(error.message));
};

$("budget-save").onclick = async () => {
  $("budget-err").textContent = "";
  try {
    await api("/api/app/budgets", { method: "POST", body: JSON.stringify({
      category: $("budget-cat").value,
      limit: $("budget-limit").value,
    })});
    $("budget-limit").value = "";
    haptic("success"); toast("Бюджет сохранён");
    await loadBudgets(); await loadHome();
  } catch (error) { $("budget-err").textContent = error.message; }
};

$("goal-create").onclick = async () => {
  $("goal-err").textContent = "";
  try {
    await api("/api/app/goals", { method: "POST", body: JSON.stringify({
      title: $("goal-title").value,
      target: $("goal-target").value,
      initial: $("goal-initial").value || 0,
      icon: $("goal-icon").value || "🎯",
    })});
    $("goal-title").value = ""; $("goal-target").value = ""; $("goal-initial").value = "";
    haptic("success"); toast("Цель создана");
    await loadGoals(); await loadHome();
  } catch (error) { $("goal-err").textContent = error.message; }
};
$("goal-list").onclick = async (event) => {
  const card = event.target.closest("[data-goal]");
  if (!card) return;
  try {
    if (event.target.closest("[data-goal-add]")) {
      await api(`/api/app/goals/${card.dataset.goal}/add`, { method: "POST", body: JSON.stringify({ amount: card.querySelector("[data-goal-amount]").value }) });
    } else if (event.target.closest("[data-goal-delete]")) {
      if (!await confirmAction("Удалить эту цель? История её пополнений не ведётся.")) return;
      await api(`/api/app/goals/${card.dataset.goal}`, { method: "DELETE" });
    } else return;
    haptic("success"); await loadGoals(); await loadHome();
  } catch (error) { toast(error.message); }
};

$("settings-save").onclick = saveSettings;
$("theme-setting").onchange = () => setTheme($("theme-setting").value);
$("export-xlsx").onclick = exportWorkbook;
$("delete-data").onclick = deleteAllData;
$("toggle-balance").onclick = () => {
  state.balanceVisible = !state.balanceVisible;
  $("toggle-balance").textContent = state.balanceVisible ? "◉" : "⊘";
  loadHome().catch((error) => toast(error.message));
};
$("open-profile").onclick = () => show("profile");
$("toast").onclick = async (event) => {
  const button = event.target.closest("[data-undo]");
  if (!button) return;
  try {
    await api(`/api/app/transactions/${button.dataset.undo}/restore`, { method: "POST" });
    $("toast").style.display = "none";
    toast("Удаление отменено");
    await loadHistory(); await loadHome();
  } catch (error) { toast(error.message); }
};

$("dev-enter").onclick = async () => {
  headers.Authorization = `Bearer ${$("dev-token").value.trim()}`;
  try { await boot(); } catch (error) { $("login-err").textContent = error.message; }
};

window.addEventListener("resize", () => {
  if (state.activeScreen === "analytics") loadAnalytics(state.analyticsPeriod).catch(() => {});
});

if (tg && tg.initData) {
  boot().catch((error) => {
    $("login").classList.add("on");
    $("login-err").textContent = error.message;
  });
} else {
  $("login").classList.add("on");
}
