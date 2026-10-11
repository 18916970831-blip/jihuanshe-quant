const charts = [];
const state = { dashboard: null, code: null, showExtreme: false, readonly: false };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  const n = Number(value) * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function cny(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return `¥${n.toLocaleString("zh-CN", { maximumFractionDigits: n % 1 ? 2 : 0 })}`;
}

function num(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function share(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function tone(value) {
  if (value === null || value === undefined || Number(value) === 0) return "flat";
  return Number(value) > 0 ? "up" : "down";
}

function chip(action) {
  const sell = action && action.includes("卖");
  const buy = action && action.includes("买");
  const wait = action === "观望" || action === "持有观察";
  const cls = sell ? "sell" : buy ? "buy" : wait ? "wait" : "";
  return `<span class="chip ${cls}">${esc(action || "—")}</span>`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : body;
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  return body;
}

function clearCharts() {
  while (charts.length) charts.pop().dispose();
}

function mountChart(el, option) {
  if (!window.echarts || !el) return null;
  const chart = echarts.init(el, null, { renderer: "canvas" });
  chart.setOption(option);
  charts.push(chart);
  return chart;
}

window.addEventListener("resize", () => charts.forEach((chart) => chart.resize()));

function axisText() {
  return { color: "#6f675c", fontFamily: "Avenir Next, PingFang SC, sans-serif" };
}

function baseGrid(extra = {}) {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Avenir Next, PingFang SC, sans-serif", color: "#1d1914" },
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 18, top: 36, bottom: 58 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    ...extra,
  };
}

function priceOption(series, showExtreme) {
  const rows = series.daily || series || [];
  const medians = rows.map((row) => row.median).filter((value) => value != null);
  const low = Math.min(...medians);
  const high = Math.max(...medians);
  const capHigh = high * 1.35;
  const capLow = low * 0.7;
  const outliers = showExtreme ? (series.outliers || []).filter((row) => row.price <= capHigh && row.price >= capLow) : [];
  const legend = ["日中位价", "7日均线", "30日均线"].concat(outliers.length ? ["异常点"] : []);
  return {
    ...baseGrid({ legend: { data: legend, top: 0, textStyle: axisText() } }),
    xAxis: { type: "category", data: rows.map((row) => row.date.slice(5)), axisLabel: axisText() },
    yAxis: { type: "value", scale: true, axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: [
      { name: "日中位价", type: "line", data: rows.map((row) => row.median), showSymbol: false, lineStyle: { width: 2, color: "#1d1914" }, itemStyle: { color: "#1d1914" } },
      { name: "7日均线", type: "line", data: rows.map((row) => row.ma7), showSymbol: false, lineStyle: { width: 1.4, color: "#8d5b28" }, itemStyle: { color: "#8d5b28" } },
      { name: "30日均线", type: "line", data: rows.map((row) => row.ma30), showSymbol: false, lineStyle: { width: 1.4, color: "#2f5d73" }, itemStyle: { color: "#2f5d73" } },
      { name: "异常点", type: "scatter", data: outliers.map((row) => [row.date.slice(5), row.price]), itemStyle: { color: "#b4332a" } },
    ],
  };
}

function volumeOption(rows) {
  return {
    ...baseGrid(),
    xAxis: { type: "category", data: rows.map((row) => row.date.slice(5)), axisLabel: axisText() },
    yAxis: { type: "value", axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: [
      { name: "成交笔数", type: "bar", data: rows.map((row) => row.count), itemStyle: { color: "#d8c4a4" } },
      { name: "7日均量", type: "line", data: rows.map((row) => row.volume_ma7), showSymbol: false, lineStyle: { color: "#8d5b28" }, itemStyle: { color: "#8d5b28" } },
    ],
  };
}

function overlayOption(rows) {
  return {
    ...baseGrid({ grid: { left: 48, right: 42, top: 28, bottom: 58 } }),
    xAxis: { type: "category", data: rows.map((row) => row.date.slice(5)), axisLabel: axisText() },
    yAxis: [
      { type: "value", scale: true, axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
      { type: "value", axisLabel: axisText(), splitLine: { show: false } },
    ],
    series: [
      { name: "价格", type: "line", data: rows.map((row) => row.median), showSymbol: false, lineStyle: { color: "#1d1914", width: 2 }, itemStyle: { color: "#1d1914" } },
      { name: "成交量", type: "bar", yAxisIndex: 1, data: rows.map((row) => row.count), itemStyle: { color: "rgba(180,51,42,0.35)" } },
    ],
  };
}

function lineOption(rows, key, name, scale = true) {
  return {
    ...baseGrid(),
    xAxis: { type: "category", data: rows.map((row) => row.date.slice(5)), axisLabel: axisText() },
    yAxis: { type: "value", scale, axisLabel: { ...axisText(), formatter: (v) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: [{ name, type: "line", data: rows.map((row) => row[key]), showSymbol: false, lineStyle: { color: "#b4332a", width: 1.8 }, areaStyle: { color: "rgba(180,51,42,0.08)" }, itemStyle: { color: "#b4332a" } }],
  };
}

function spark(points) {
  const values = (points || []).map((point) => point.median).filter((value) => value != null);
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const coords = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 120;
    const y = max === min ? 18 : 34 - ((value - min) / (max - min)) * 30;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const color = values.at(-1) >= values[0] ? "#1d7a4a" : "#b4332a";
  return `<svg class="spark" viewBox="0 0 120 36" preserveAspectRatio="none"><polyline points="${coords}" fill="none" stroke="${color}" stroke-width="1.8" /></svg>`;
}

function setActive(view) {
  document.querySelectorAll(".nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    state.readonly = !!status.readonly;
    document.querySelectorAll("[data-owner]").forEach((el) => {
      el.hidden = state.readonly;
    });
    const suffix = state.readonly ? " · 只读分享" : "";
    const syncNote = status.sync === "waiting" || status.sync === "pushing" ? " · 正在同步到公网" : status.sync === "error" ? " · 公网同步失败，本机分析已更新" : "";
    document.getElementById("status").textContent = status.as_of
      ? `样本截止 ${status.as_of} · ${status.cards} 张卡 · ${status.trades} 笔成交 · ${status.alerts_open} 条未读告警${suffix}${syncNote}`
      : "还没有成交数据";
  } catch (error) {
    document.getElementById("status").textContent = error.message;
  }
}

function ownerOnly(root, title) {
  if (!state.readonly) return false;
  root.innerHTML = `<section class="panel"><h2>${esc(title)}</h2><p class="note">这是分享页，只能看总览、对比、报告和告警。改数据要在这台电脑上打开。</p></section>`;
  return true;
}

function viewRoot() {
  clearCharts();
  const root = document.getElementById("view");
  root.innerHTML = `<div class="panel">正在计算…</div>`;
  return root;
}

async function renderDashboard() {
  const root = viewRoot();
  const data = await api("/api/dashboard");
  state.dashboard = data;
  if (!state.code && data.cards.length) state.code = data.cards[0].card_code;
  root.innerHTML = `
    <div class="stack">
      <section class="panel brief">${data.briefing.map((line) => `<p>${esc(line)}</p>`).join("")}</section>
      <section class="grid-cards">${data.cards.map((card) => `
        <button class="tile ${card.card_code === state.code ? "active" : ""}" data-code="${esc(card.card_code)}">
          <div class="code">${esc(card.card_code)} · ${esc(card.card_series || "")}</div>
          <div>${esc(card.card_name)}</div>
          <div class="price">${cny(card.latest_price)}</div>
          <div class="kv"><span>7日 <b class="${tone(card.return_7d)}">${pct(card.return_7d)}</b></span><span>30日 <b class="${tone(card.return_30d)}">${pct(card.return_30d)}</b></span></div>
          <div class="kv"><span>量变 <b class="${tone(card.volume_change_7d)}">${pct(card.volume_change_7d)}</b></span>${chip(card.advice && card.advice.action)}</div>
          ${spark(card.sparkline)}
        </button>`).join("") || `<div class="panel">还没有卡牌。去「导入」放入集换社 Excel。</div>`}
      </section>
      <section class="grid-2">
        <div class="panel chart-card">
          <h3>PSA10 日中位价</h3>
          <p class="sub" id="dash-caption"></p>
          <div id="dash-chart" class="chart tall"></div>
        </div>
        <div class="stack">
          <div class="panel">
            <h3>告警</h3>
            ${data.alerts.length ? `<ul class="list">${data.alerts.slice(0, 6).map((alert) => `<li><b class="level-${esc(alert.level)}">${esc(alert.title)}</b> ${esc(alert.message)}</li>`).join("")}</ul>` : `<p class="note">当前没有触发中的告警。</p>`}
          </div>
          <div class="panel">
            <h3>事件</h3>
            ${data.events.length ? `<ul class="list">${data.events.map((event) => `<li>${esc(event.event_date)} · ${esc(event.title)}</li>`).join("")}</ul>` : `<p class="note">事件库是空的。</p>`}
          </div>
        </div>
      </section>
    </div>`;
  root.querySelectorAll("[data-code]").forEach((button) => {
    button.onclick = () => {
      state.code = button.dataset.code;
      renderDashboard();
    };
    button.ondblclick = () => { location.hash = `#/card/${button.dataset.code}`; };
  });
  if (state.code) loadDashChart(state.code);
}

async function loadDashChart(code) {
  const metrics = await api(`/api/cards/${encodeURIComponent(code)}/analysis`);
  const caption = document.getElementById("dash-caption");
  if (caption) caption.textContent = `${metrics.card_name} · 双击卡片进入完整分析。棕色是 7 日均线，蓝色是 30 日均线。`;
  mountChart(document.getElementById("dash-chart"), priceOption({ daily: metrics.series, outliers: metrics.anomalies }, false));
}

async function renderCard(code) {
  const root = viewRoot();
  const metrics = await api(`/api/cards/${encodeURIComponent(code)}/analysis`);
  state.code = code;
  const advice = metrics.advice || {};
  const returns = metrics.returns || {};
  const volume = metrics.volume || {};
  const risk = metrics.risk || {};
  root.innerHTML = `
    <div class="stack">
      <section class="panel">
        <div class="code">${esc(metrics.card_code)} · ${esc(metrics.card_series || "")} ${metrics.region ? "· " + esc(metrics.region) : ""}</div>
        <h2>${esc(metrics.card_name)} ${chip(advice.action)}</h2>
        <p class="sub">${esc((metrics.warnings || []).join(" · ") || `样本 ${metrics.sample_start || "—"} 至 ${metrics.sample_end || "—"} · PSA10 ${metrics.psa10_count} 笔 · 套出 ${metrics.bundle_count} 笔已剔除`)}</p>
        <div class="metrics">
          ${metric("最新价", cny(metrics.latest_price))}
          ${metric("7日收益", pct((returns.d7 || {}).return), tone((returns.d7 || {}).return))}
          ${metric("30日收益", pct((returns.d30 || {}).return), tone((returns.d30 || {}).return))}
          ${metric("90日收益", pct((returns.d90 || {}).return), tone((returns.d90 || {}).return))}
          ${metric("7日量 / 量变", `${num(volume.d7)} / ${pct(volume.change_7d)}`)}
          ${metric("波动率", share(risk.volatility))}
          ${metric("最大回撤", pct(risk.max_drawdown), "down")}
          ${metric("价格分位", share(metrics.percentile))}
        </div>
      </section>
      <section class="panel">
        <h3>读数</h3>
        <p>${esc(narrative(metrics))}</p>
        <p class="note">曲线是每日全部 PSA10 成交的中位价。单笔异常默认不拉高坐标，样本最高 ${cny(metrics.high_raw)}。日均成交 ${num(volume.avg_active)} 笔，有效交易日占比 ${share(volume.active_ratio)}。</p>
        <label class="check"><input id="extreme" type="checkbox" ${state.showExtreme ? "checked" : ""}/> 在价格图里拉伸坐标，显示极端异常点</label>
      </section>
      <section class="charts">
        ${chartBox("c1", "日中位价", "含 7 日 / 30 日均线，可缩放")}
        ${chartBox("c2", "日成交量", "柱为当日笔数，线为 7 日均量")}
        ${chartBox("c3", "价量叠加", "左轴价格，右轴成交笔数")}
        ${chartBox("c5", "滚动波动率", "相邻交易日收益的 7 日滚动标准差")}
        ${chartBox("c6", "回撤", "相对样本内历史高点")}
        ${chartBox("c7", "价格分布", "当前价落在标红区间")}
        ${chartBox("c8", "竞价", "有多日快照时看趋势，否则看买盘梯队")}
        ${chartBox("c9", "异常成交", "红点为规则命中的成交")}
      </section>
      <section class="grid-2">
        <div class="panel">
          <h3>规则建议</h3>
          <p>${chip(advice.action)} 仓位：${esc(advice.position || "—")}</p>
          <p>止盈 ${cny(advice.take_profit)} · 止损 ${cny(advice.stop_loss)}</p>
          <ul class="list">${(advice.reasons || []).map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul>
          <p class="note">${esc((metrics.prediction || {}).disclaimer || "")}</p>
        </div>
        <div class="panel">
          <h3>预测区间</h3>
          ${predictionBlock(metrics.prediction)}
        </div>
      </section>
      ${tablePanel("异常成交", anomalyTable(metrics.anomalies), "这些成交保留在库里，但不进入主价格曲线。")}
      ${tablePanel("套出观察", bundleTable(metrics.bundle_trades), "套出、套卡、打包，以及名称里带 + 的记录。")}
      ${tablePanel("品相分布", gradeTable(metrics.grade_mix), "只有 PSA10 且非套出进入收益、波动和预测。")}
    </div>`;
  document.getElementById("extreme").onchange = (event) => {
    state.showExtreme = event.target.checked;
    drawCardCharts(metrics);
  };
  drawCardCharts(metrics);
}

function metric(label, value, className = "") {
  return `<div><div class="note">${esc(label)}</div><div class="mono ${className}" style="font-size:20px">${value}</div></div>`;
}

function chartBox(id, title, sub) {
  return `<div class="panel chart-card"><h3>${esc(title)}</h3><p class="sub">${esc(sub)}</p><div id="${id}" class="chart"></div></div>`;
}

function narrative(metrics) {
  if (!metrics.has_psa10) return "这张卡没有可计价的 PSA10 成交。";
  const signal = (metrics.divergence || {}).signal;
  return `${metrics.card_name} 最新中位价 ${cny(metrics.latest_price)}。近 7 日 ${pct((metrics.returns.d7 || {}).return)}，近 30 日 ${pct((metrics.returns.d30 || {}).return)}，量价信号是${signal}。${(metrics.divergence || {}).meaning || ""}`;
}

function predictionBlock(prediction) {
  if (!prediction || !prediction.available) return `<p>${esc((prediction && prediction.reason) || "样本不足")}</p>`;
  return `<p>7 日 ${cny(prediction.d7.low)} – ${cny(prediction.d7.high)}</p>
    <p>30 日 ${cny(prediction.d30.low)} – ${cny(prediction.d30.high)}</p>
    <p>基准判断 ${esc(prediction.bias)}，拟合 R² ${num(prediction.r2)}</p>`;
}

function anomalyTable(rows) {
  if (!rows || !rows.length) return `<p class="note">没有命中异常规则的成交。</p>`;
  return `<table><tr><th>日期</th><th>时间</th><th>价格</th><th>原因</th></tr>${rows.map((row) => `<tr><td>${esc(row.date)}</td><td class="mono">${esc(row.time || "")}</td><td class="mono">${cny(row.price)}</td><td>${esc((row.reasons || []).join("、"))}</td></tr>`).join("")}</table>`;
}

function bundleTable(rows) {
  if (!rows || !rows.length) return `<p class="note">没有套出记录。</p>`;
  return `<table><tr><th>日期</th><th>价格</th><th>品相</th><th>名称</th></tr>${rows.map((row) => `<tr><td>${esc(row.date)}</td><td class="mono">${cny(row.price)}</td><td>${esc(row.grade)}</td><td>${esc(row.name || "")}</td></tr>`).join("")}</table>`;
}

function gradeTable(rows) {
  if (!rows || !rows.length) return `<p class="note">无记录。</p>`;
  return `<table><tr><th>品相</th><th>笔数</th></tr>${rows.map((row) => `<tr><td>${esc(row.grade)}</td><td class="mono">${row.count}</td></tr>`).join("")}</table>`;
}

function tablePanel(title, html, sub) {
  return `<section class="panel"><h3>${esc(title)}</h3><p class="sub">${esc(sub)}</p>${html}</section>`;
}

function drawCardCharts(metrics) {
  clearCharts();
  const rows = metrics.series || [];
  mountChart(document.getElementById("c1"), priceOption({ daily: rows, outliers: metrics.anomalies }, state.showExtreme));
  mountChart(document.getElementById("c2"), volumeOption(rows));
  mountChart(document.getElementById("c3"), overlayOption(rows));
  mountChart(document.getElementById("c5"), lineOption(rows.filter((row) => row.volatility != null), "volatility", "波动率"));
  mountChart(document.getElementById("c6"), lineOption(rows, "drawdown", "回撤"));
  const hist = metrics.histogram || [];
  mountChart(document.getElementById("c7"), {
    ...baseGrid({ tooltip: { trigger: "axis" } }),
    xAxis: { type: "category", data: hist.map((bin) => `${Math.round(bin.left)}-${Math.round(bin.right)}`), axisLabel: { ...axisText(), rotate: 30 } },
    yAxis: { type: "value", axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: [{ type: "bar", data: hist.map((bin) => ({ value: bin.count, itemStyle: { color: bin.contains_latest ? "#b4332a" : "#d8c4a4" } })) }],
  });
  const bids = metrics.bids || [];
  if (bids.length > 1) {
    mountChart(document.getElementById("c8"), {
      ...baseGrid(),
      xAxis: { type: "category", data: bids.map((bid) => bid.date), axisLabel: axisText() },
      yAxis: { type: "value", scale: true, axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
      series: [
        { name: "最高竞价", type: "line", data: bids.map((bid) => bid.highest_bid), itemStyle: { color: "#1d1914" } },
        { name: "最低卖价", type: "line", data: bids.map((bid) => bid.lowest_ask), itemStyle: { color: "#b4332a" } },
      ],
    });
  } else if (bids.length === 1 && (bids[0].ladder || []).length) {
    mountChart(document.getElementById("c8"), {
      ...baseGrid({ dataZoom: [] }),
      xAxis: { type: "category", data: bids[0].ladder.map((_, index) => `第 ${index + 1} 档`), axisLabel: axisText() },
      yAxis: { type: "value", scale: true, axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
      series: [{ type: "bar", data: bids[0].ladder, itemStyle: { color: "#2f5d73" } }],
    });
  }
  mountChart(document.getElementById("c9"), priceOption({ daily: rows, outliers: metrics.anomalies }, true));
}

async function renderCompare() {
  const root = viewRoot();
  const data = await api("/api/compare");
  root.innerHTML = `
    <div class="stack">
      <section class="charts">
        <div class="panel chart-card"><h3>收益对比</h3><p class="sub">7 日 / 30 日 / 90 日</p><div id="c4" class="chart tall"></div></div>
        <div class="panel chart-card"><h3>归一化价格</h3><p class="sub">各卡第一笔有效中位价 = 100</p><div id="c10" class="chart tall"></div></div>
      </section>
      <section class="panel"><table>
        <tr><th>卡牌</th><th>最新价</th><th>7D</th><th>30D</th><th>90D</th><th>波动率</th><th>回撤</th><th>日均量</th><th>供给</th><th>建议</th></tr>
        ${data.cards.map((card) => `<tr>
          <td><a href="#/card/${esc(card.card_code)}">${esc(card.card_name)}</a></td>
          <td class="mono">${cny(card.latest_price)}</td>
          <td class="mono ${tone(card.return_7d)}">${pct(card.return_7d)}</td>
          <td class="mono ${tone(card.return_30d)}">${pct(card.return_30d)}</td>
          <td class="mono ${tone(card.return_90d)}">${pct(card.return_90d)}</td>
          <td class="mono">${share(card.volatility)}</td>
          <td class="mono">${pct(card.max_drawdown)}</td>
          <td class="mono">${num(card.avg_active)}</td>
          <td>${esc((card.population && card.population.pressure && card.population.pressure.label) || "—")}</td>
          <td>${chip(card.advice && card.advice.action)}</td>
        </tr>`).join("")}
      </table></section>
    </div>`;
  const names = data.cards.map((card) => card.card_name);
  mountChart(document.getElementById("c4"), {
    ...baseGrid({ legend: { top: 0 }, tooltip: { trigger: "axis" } }),
    xAxis: { type: "category", data: names, axisLabel: { ...axisText(), rotate: 20 } },
    yAxis: { type: "value", axisLabel: { ...axisText(), formatter: (v) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: [
      { name: "7D", type: "bar", data: data.cards.map((card) => card.return_7d) },
      { name: "30D", type: "bar", data: data.cards.map((card) => card.return_30d) },
      { name: "90D", type: "bar", data: data.cards.map((card) => card.return_90d) },
    ],
  });
  const dates = [...new Set(data.cards.flatMap((card) => card.normalized.map((point) => point.date)))].sort();
  const palette = ["#1d1914", "#b4332a", "#8d5b28", "#2f5d73", "#1d7a4a", "#6d4b8a"];
  mountChart(document.getElementById("c10"), {
    ...baseGrid({ legend: { top: 0, type: "scroll" } }),
    xAxis: { type: "category", data: dates.map((item) => item.slice(5)), axisLabel: axisText() },
    yAxis: { type: "value", scale: true, axisLabel: axisText(), splitLine: { lineStyle: { color: "#efe6d6" } } },
    series: data.cards.map((card, index) => {
      const lookup = Object.fromEntries(card.normalized.map((point) => [point.date, point.index]));
      return { name: card.card_name, type: "line", showSymbol: false, data: dates.map((item) => lookup[item] ?? null), connectNulls: true, lineStyle: { color: palette[index % palette.length] }, itemStyle: { color: palette[index % palette.length] } };
    }),
  });
}

async function renderEntry() {
  const root = viewRoot();
  if (ownerOnly(root, "录入")) return;
  const [cards, trades] = await Promise.all([api("/api/cards"), api("/api/trades?limit=12")]);
  const today = new Date().toISOString().slice(0, 10);
  root.innerHTML = `
    <div class="stack">
      <section class="panel">
        <h2>录入一笔成交</h2>
        <p class="sub">品相会自动归并，备注里出现套出、套卡、打包会标成套出，不进 PSA10 计价。</p>
        <form id="trade-form" class="form">
          <label>卡牌<select name="card_code" required>${cards.map((card) => `<option value="${esc(card.card_code)}">${esc(card.card_code)} ${esc(card.card_name)}</option>`).join("")}</select></label>
          <label>日期<input name="trade_date" type="date" value="${today}" required /></label>
          <label>时间<input name="trade_time" type="time" value="20:00" /></label>
          <label>成交价<input name="price" type="number" min="0.01" step="0.01" required /></label>
          <label>品相<select name="grade"><option>PSA10</option><option>PSA9</option><option>PSA8</option><option>PCG10</option><option>BGS10</option><option>其他</option></select></label>
          <label class="check">标记套出<input name="mark_bundle" type="checkbox" /></label>
          <label class="span-3">备注<textarea name="notes" placeholder="可选"></textarea></label>
          <div class="span-3 actions"><button class="btn" type="submit">保存</button><span id="trade-msg" class="note"></span></div>
        </form>
      </section>
      <section class="panel">
        <h3>最近成交</h3>
        ${tradeRows(trades)}
      </section>
    </div>`;
  document.getElementById("trade-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    const payload = {
      card_code: form.card_code.value,
      trade_date: form.trade_date.value,
      trade_time: form.trade_time.value ? `${form.trade_time.value}:00` : null,
      price: Number(form.price.value),
      grade: form.grade.value,
      notes: form.notes.value || null,
      mark_bundle: form.mark_bundle.checked,
    };
    await submitTrade(payload, false);
  };
}

async function submitTrade(payload, force) {
  const msg = document.getElementById("trade-msg");
  try {
    const result = await api(`/api/trades?force=${force ? "true" : "false"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    msg.className = "ok";
    msg.textContent = `已保存。当日 PSA10 真实成交 ${result.today.count} 笔，中位价 ${cny(result.today.median)}。分析已重算，公网页面大约一两分钟后自动跟上。`;
    refreshStatus();
  } catch (error) {
    if (!force && error.message.includes("强制")) {
      if (confirm(`${error.message}\n仍然保存？`)) return submitTrade(payload, true);
    }
    msg.className = "error";
    msg.textContent = error.message;
  }
}

function tradeRows(trades) {
  if (!trades.length) return `<p class="note">还没有成交。</p>`;
  return `<table><tr><th>时间</th><th>卡牌</th><th>价格</th><th>品相</th><th>套出</th><th></th></tr>
    ${trades.map((row) => `<tr>
      <td class="mono">${esc(row.trade_date)} ${esc((row.trade_time || "").slice(0, 5))}</td>
      <td>${esc(row.card_code)}</td>
      <td class="mono">${cny(row.price)}</td>
      <td>${esc(row.grade)}</td>
      <td>${row.is_bundle ? "是" : ""}</td>
      <td><button class="btn ghost small" data-del="${esc(row.id)}">删除</button></td>
    </tr>`).join("")}</table>`;
}

async function renderImport() {
  const root = viewRoot();
  if (ownerOnly(root, "导入")) return;
  const logs = await api("/api/imports");
  root.innerHTML = `
    <div class="stack">
      <section class="panel">
        <h2>导入 Excel</h2>
        <p class="sub">支持现有汇总表。每个成交 Sheet 一种卡，竞价 Sheet 单独识别。重复的同卡同时同价记录会跳过。</p>
        <form id="import-form" class="drop">
          <input id="file" type="file" accept=".xlsx" required />
          <div class="actions" style="justify-content:center;margin-top:12px"><button class="btn" type="submit">开始导入</button></div>
        </form>
        <div id="import-result"></div>
      </section>
      <section class="panel">
        <h3>最近导入</h3>
        ${logs.length ? `<table><tr><th>时间</th><th>文件</th><th>成功</th><th>失败</th><th>跳过</th></tr>${logs.map((row) => `<tr><td class="mono">${esc(row.created_at)}</td><td>${esc(row.filename)}</td><td>${row.success}</td><td>${row.failed}</td><td>${row.skipped}</td></tr>`).join("")}</table>` : `<p class="note">还没有导入记录。</p>`}
      </section>
    </div>`;
  document.getElementById("import-form").onsubmit = async (event) => {
    event.preventDefault();
    const box = document.getElementById("import-result");
    const data = new FormData();
    data.append("file", document.getElementById("file").files[0]);
    box.innerHTML = `<p class="note">正在清洗并计算…</p>`;
    try {
      const result = await api("/api/import", { method: "POST", body: data });
      box.innerHTML = `<div class="ok" style="margin-top:12px">成功 ${result.success}，失败 ${result.failed}，跳过 ${result.skipped}。分析已重算，公网页面大约一两分钟后自动跟上。</div>
        <table><tr><th>Sheet</th><th>代码</th><th>成功</th><th>失败</th><th>跳过</th></tr>
        ${result.sheets.map((sheet) => `<tr><td>${esc(sheet.sheet)}</td><td class="mono">${esc(sheet.card_code || "—")}</td><td>${sheet.success}</td><td>${sheet.failed}</td><td>${sheet.skipped}</td></tr>`).join("")}</table>`;
      refreshStatus();
    } catch (error) {
      box.innerHTML = `<div class="error">${esc(error.message)}</div>`;
    }
  };
}

async function renderReport() {
  const root = viewRoot();
  const report = await api("/api/report");
  root.innerHTML = `
    <article class="doc">
      <div class="actions no-print">
        <a class="btn" href="/api/report.docx">导出 Word</a>
        <a class="btn ghost" href="/api/report.xlsx">导出 Excel</a>
        <button class="btn ghost" id="print">打印 / PDF</button>
      </div>
      <p class="note">${esc(report.generated_at)} · 截止 ${esc(report.as_of || "—")}</p>
      <h2 style="margin-top:8px">${esc(report.title)}</h2>
      <p>${esc(report.disclaimer)}</p>
      <h2>1. 管理层结论</h2>
      <ul class="list">${report.executive.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <h2>2. 核心量化指标</h2>
      <table><tr><th>卡牌</th><th>最新价</th><th>7D</th><th>30D</th><th>7D量</th><th>量变</th><th>波动率</th><th>回撤</th><th>建议</th></tr>
        ${report.metrics_table.map((row) => `<tr>
          <td>${esc(row.card_name)}</td><td class="mono">${cny(row.latest_price)}</td>
          <td class="mono ${tone(row.return_7d)}">${pct(row.return_7d)}</td>
          <td class="mono ${tone(row.return_30d)}">${pct(row.return_30d)}</td>
          <td class="mono">${num(row.volume_7d)}</td>
          <td class="mono ${tone(row.volume_change_7d)}">${pct(row.volume_change_7d)}</td>
          <td class="mono">${share(row.volatility)}</td>
          <td class="mono">${pct(row.max_drawdown)}</td>
          <td>${chip(row.action)}</td></tr>`).join("")}
      </table>
      <h2>3. PSA10 专项分析</h2>
      ${report.cards.map((card, index) => `<section class="chapter"><h3>${esc(card.card_name)}</h3><p>${esc(card.narrative)}</p><div id="report-${index}" class="chart"></div></section>`).join("")}
      <h2>4. 价格 / 成交量背离与热度</h2>
      <table><tr><th>卡牌</th><th>信号</th><th>7D</th><th>量变</th><th>热度</th><th>含义</th></tr>
        ${report.divergence.map((row) => `<tr><td>${esc(row.card_name)}</td><td>${esc(row.signal)}</td><td class="mono">${pct(row.return_7d)}</td><td class="mono">${pct(row.volume_change_7d)}</td><td class="mono">${num(row.heat)}</td><td>${esc(row.meaning)}</td></tr>`).join("")}
      </table>
      <h2>5. 流动性与供需</h2>
      <table><tr><th>卡牌</th><th>有效交易日</th><th>日均量</th><th>成交间隔</th><th>最高竞价</th><th>供给压力</th></tr>
        ${report.liquidity.map((row) => `<tr><td>${esc(row.card_name)}</td><td>${share(row.active_ratio)}</td><td>${num(row.avg_active)}</td><td>${num(row.median_gap_hours)} 小时</td><td>${cny(row.highest_bid)}</td><td>${esc(row.pressure || "—")} ${row.pressure_score ?? ""}</td></tr>`).join("")}
      </table>
      <h2>6. 异常成交</h2>
      ${report.anomalies.length ? report.anomalies.map((block) => `<h3>${esc(block.card_name)} · ${block.count} 笔</h3>${anomalyTable(block.rows)}`).join("") : `<p>没有异常成交。</p>`}
      <h2>7. 未来价格预测</h2>
      ${report.forecasts.map((row) => `<p><b>${esc(row.card_name)}</b> ${row.available ? `7 日 ${cny(row.d7.low)}–${cny(row.d7.high)}，30 日 ${cny(row.d30.low)}–${cny(row.d30.high)}，${esc(row.bias)}。${esc(row.action_hint)}` : esc(row.reason)}</p>`).join("")}
      <p class="note">${esc(report.forecasts[0] ? report.forecasts[0].disclaimer : "")}</p>
      <h2>8. 投资建议</h2>
      ${report.advice.ranking.map((row) => `<p><b>${esc(row.card_name)}</b> ${chip(row.action)} 评分 ${num(row.score)}。${esc(row.position)} 止盈 ${cny(row.take_profit)}，止损 ${cny(row.stop_loss)}。</p><ul class="list">${row.reasons.map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul>`).join("")}
      <ul class="list">${report.advice.risk_controls.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <h2>9. 外部市场核验与事件</h2>
      <p>${esc(report.external.note)}</p>
      <table><tr><th>卡牌</th><th>总人口</th><th>PSA10</th><th>Gem Rate</th><th>压力</th></tr>
        ${report.external.population.map((row) => `<tr><td>${esc(row.card_name)}</td><td class="mono">${num(row.total)}</td><td class="mono">${num(row.psa10)}</td><td class="mono">${share(row.gem_rate)}</td><td>${esc(row.pressure || "—")}</td></tr>`).join("")}
      </table>
      <ul class="list">${report.external.events.map((event) => `<li>${esc(event.date)} [${esc(event.impact_level || "—")}] ${esc(event.title)}。${esc(event.description || "")}</li>`).join("")}</ul>
      <h2>10. 建议后续监控</h2>
      ${report.monitoring.map((block) => `<ul class="list">${block.tips.map((tip) => `<li>${esc(tip)}</li>`).join("")}</ul>`).join("")}
    </article>`;
  document.getElementById("print").onclick = () => window.print();
  report.cards.forEach((card, index) => {
    if (card.series && card.series.length) mountChart(document.getElementById(`report-${index}`), priceOption({ daily: card.series, outliers: [] }, false));
  });
}

async function renderAlerts() {
  const root = viewRoot();
  const alerts = await api("/api/alerts?active_only=false");
  root.innerHTML = `
    <section class="panel stack">
      <div class="actions"><h2 style="margin:0">告警</h2>${state.readonly ? "" : `<button class="btn" id="scan">重新扫描</button><button class="btn ghost" id="read-all">全部已读</button>`}</div>
      <p class="sub">暴涨、暴跌、放量、IQR 异常、竞价偏离、高影响供给事件、波动率飙升。条件消失后告警会自动关掉。</p>
      ${alerts.length ? `<table><tr><th>状态</th><th>级别</th><th>规则</th><th>内容</th><th></th></tr>
        ${alerts.map((alert) => `<tr>
          <td>${alert.is_active ? "触发" : "已解除"}</td>
          <td class="level-${esc(alert.level)}">${esc(alert.level)}</td>
          <td>${esc(alert.rule_id)} ${esc(alert.title)}</td>
          <td>${esc(alert.message)}</td>
          <td>${!state.readonly && alert.is_active && !alert.is_read ? `<button class="btn ghost small" data-read="${esc(alert.id)}">已读</button>` : ""}</td>
        </tr>`).join("")}</table>` : `<p class="note">没有告警。</p>`}
    </section>`;
  if (!state.readonly) {
    document.getElementById("scan").onclick = async () => { await api("/api/alerts/scan", { method: "POST" }); renderAlerts(); refreshStatus(); };
    document.getElementById("read-all").onclick = async () => { await api("/api/alerts/read-all", { method: "POST" }); renderAlerts(); refreshStatus(); };
  }
  root.querySelectorAll("[data-read]").forEach((button) => {
    button.onclick = async () => { await api(`/api/alerts/${button.dataset.read}/read`, { method: "POST" }); renderAlerts(); refreshStatus(); };
  });
}

async function renderLibrary() {
  const root = viewRoot();
  if (ownerOnly(root, "卡牌库")) return;
  const [cards, events, bids, meta, audit] = await Promise.all([
    api("/api/cards"), api("/api/events"), api("/api/bids"), api("/api/meta"), api("/api/audit"),
  ]);
  root.innerHTML = `
    <div class="stack">
      <section class="panel">
        <h2>卡牌与 PSA 人口</h2>
        <table><tr><th>代码</th><th>名称</th><th>系列</th><th>总人口</th><th>PSA10</th><th>Gem</th><th>关注</th><th></th></tr>
          ${cards.map((card) => `<tr data-card="${esc(card.card_code)}">
            <td class="mono">${esc(card.card_code)}</td>
            <td><input value="${esc(card.card_name)}" data-field="card_name" /></td>
            <td><input value="${esc(card.card_series || "")}" data-field="card_series" /></td>
            <td><input value="${card.psa_population_total ?? ""}" data-field="psa_population_total" /></td>
            <td><input value="${card.psa_population_10 ?? ""}" data-field="psa_population_10" /></td>
            <td class="mono">${share(card.psa_gem_rate)}</td>
            <td>${card.is_active ? "是" : "否"}</td>
            <td><button class="btn small" data-save="${esc(card.card_code)}">保存</button></td>
          </tr>`).join("")}
        </table>
        <h3>新增卡牌</h3>
        <form id="card-form" class="form">
          <label>代码<input name="card_code" required placeholder="SV-P-100" /></label>
          <label>名称<input name="card_name" required /></label>
          <label>系列<select name="card_series">${meta.series.map((item) => `<option>${esc(item)}</option>`).join("")}</select></label>
          <div class="actions"><button class="btn" type="submit">添加</button></div>
        </form>
      </section>
      <section class="grid-2">
        <div class="panel">
          <h3>事件</h3>
          <form id="event-form" class="form">
            <label>日期<input type="date" name="event_date" required /></label>
            <label>类型<select name="event_type">${meta.event_types.map((item) => `<option>${esc(item)}</option>`).join("")}</select></label>
            <label>影响<select name="impact_level">${meta.impacts.map((item) => `<option>${esc(item)}</option>`).join("")}</select></label>
            <label class="span-2">标题<input name="title" required /></label>
            <label>关联卡牌<select name="card_code"><option value="">全局</option>${cards.map((card) => `<option value="${esc(card.card_code)}">${esc(card.card_code)}</option>`).join("")}</select></label>
            <label class="span-3">说明<textarea name="description"></textarea></label>
            <div><button class="btn" type="submit">记录事件</button></div>
          </form>
          <ul class="list">${events.map((event) => `<li>${esc(event.event_date)} [${esc(event.impact_level)}] ${esc(event.title)} <button class="btn ghost small" data-event="${esc(event.id)}">删除</button></li>`).join("")}</ul>
        </div>
        <div class="panel">
          <h3>竞价快照</h3>
          <form id="bid-form" class="form">
            <label>卡牌<select name="card_code">${cards.map((card) => `<option value="${esc(card.card_code)}">${esc(card.card_code)}</option>`).join("")}</select></label>
            <label>日期<input type="date" name="bid_date" required /></label>
            <label>最高竞价<input name="highest_bid" type="number" step="0.01" /></label>
            <label>第二竞价<input name="second_highest_bid" type="number" step="0.01" /></label>
            <label>最低卖价<input name="lowest_ask" type="number" step="0.01" /></label>
            <div><button class="btn" type="submit">保存竞价</button></div>
          </form>
          <table><tr><th>日期</th><th>卡牌</th><th>最高</th><th>卖价</th></tr>${bids.map((bid) => `<tr><td>${esc(bid.bid_date)}</td><td>${esc(bid.card_code)}</td><td class="mono">${cny(bid.highest_bid)}</td><td class="mono">${cny(bid.lowest_ask)}</td></tr>`).join("")}</table>
        </div>
      </section>
      <section class="panel">
        <h3>操作日志</h3>
        <ul class="list">${audit.map((row) => `<li>${esc(row.created_at)} · ${esc(row.action)} · ${esc(row.detail || "")}</li>`).join("")}</ul>
      </section>
    </div>`;
  root.querySelectorAll("[data-save]").forEach((button) => {
    button.onclick = async () => {
      const tr = button.closest("tr");
      const payload = {};
      tr.querySelectorAll("[data-field]").forEach((input) => {
        const field = input.dataset.field;
        payload[field] = field.startsWith("psa_") ? (input.value === "" ? null : Number(input.value)) : input.value;
      });
      await api(`/api/cards/${encodeURIComponent(button.dataset.save)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      renderLibrary();
    };
  });
  document.getElementById("card-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    await api("/api/cards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ card_code: form.card_code.value, card_name: form.card_name.value, card_series: form.card_series.value }) });
    renderLibrary();
  };
  document.getElementById("event-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    await api("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      event_date: form.event_date.value, event_type: form.event_type.value, impact_level: form.impact_level.value,
      title: form.title.value, description: form.description.value || null, card_code: form.card_code.value || null,
    }) });
    renderLibrary();
    refreshStatus();
  };
  document.getElementById("bid-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    await api("/api/bids", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      card_code: form.card_code.value, bid_date: form.bid_date.value,
      highest_bid: form.highest_bid.value ? Number(form.highest_bid.value) : null,
      second_highest_bid: form.second_highest_bid.value ? Number(form.second_highest_bid.value) : null,
      lowest_ask: form.lowest_ask.value ? Number(form.lowest_ask.value) : null,
    }) });
    renderLibrary();
  };
  root.querySelectorAll("[data-event]").forEach((button) => {
    button.onclick = async () => { await api(`/api/events/${button.dataset.event}`, { method: "DELETE" }); renderLibrary(); };
  });
}

const routes = [
  { test: (hash) => hash === "#/dashboard" || hash === "" || hash === "#", view: "dashboard", run: renderDashboard },
  { test: (hash) => hash.startsWith("#/card/"), view: "dashboard", run: (hash) => renderCard(decodeURIComponent(hash.slice(7))) },
  { test: (hash) => hash === "#/compare", view: "compare", run: renderCompare },
  { test: (hash) => hash === "#/entry", view: "entry", run: renderEntry },
  { test: (hash) => hash === "#/import", view: "import", run: renderImport },
  { test: (hash) => hash === "#/report", view: "report", run: renderReport },
  { test: (hash) => hash === "#/alerts", view: "alerts", run: renderAlerts },
  { test: (hash) => hash === "#/library", view: "library", run: renderLibrary },
];

async function route() {
  await refreshStatus();
  const hash = location.hash || "#/dashboard";
  const matched = routes.find((item) => item.test(hash)) || routes[0];
  setActive(matched.view);
  const root = document.getElementById("view");
  try {
    await matched.run(hash);
  } catch (error) {
    clearCharts();
    root.innerHTML = `<div class="error">${esc(error.message)}</div>`;
  }
}

document.getElementById("view").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-del]");
  if (!button) return;
  if (!confirm("删除这笔成交？")) return;
  await api(`/api/trades/${button.dataset.del}`, { method: "DELETE" });
  route();
  refreshStatus();
});

window.addEventListener("hashchange", route);
route();
