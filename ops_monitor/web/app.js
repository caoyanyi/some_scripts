const state = {
  summary: null,
  history: [],
  findings: [],
  findingsPagination: { page: 1, page_size: 20, total: 0, total_pages: 1 },
  refreshTimer: null,
  countdownTimer: null,
  nextRefreshAt: null,
};

const nodes = {
  rangeSelect: document.querySelector("#rangeSelect"),
  refreshSelect: document.querySelector("#refreshSelect"),
  refreshButton: document.querySelector("#refreshButton"),
  refreshState: document.querySelector("#refreshState"),
  statusBand: document.querySelector("#statusBand"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  lastSample: document.querySelector("#lastSample"),
  findingCount: document.querySelector("#findingCount"),
  loadValue: document.querySelector("#loadValue"),
  loadMeta: document.querySelector("#loadMeta"),
  temperatureValue: document.querySelector("#temperatureValue"),
  memoryValue: document.querySelector("#memoryValue"),
  diskValue: document.querySelector("#diskValue"),
  sampleCount: document.querySelector("#sampleCount"),
  activeFindings: document.querySelector("#activeFindings"),
  findingsTable: document.querySelector("#findingsTable"),
  historyFindingCount: document.querySelector("#historyFindingCount"),
  findingPageState: document.querySelector("#findingPageState"),
  prevFindingPage: document.querySelector("#prevFindingPage"),
  nextFindingPage: document.querySelector("#nextFindingPage"),
  topCpuList: document.querySelector("#topCpuList"),
  topMemoryList: document.querySelector("#topMemoryList"),
  topCpuTime: document.querySelector("#topCpuTime"),
  topMemoryTime: document.querySelector("#topMemoryTime"),
  chart: document.querySelector("#historyChart"),
};

function formatTime(timestamp) {
  if (!timestamp) return "--";
  return new Date(timestamp * 1000).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatNumber(value, digits = 1, suffix = "") {
  if (value === null || value === undefined) return "--";
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function statusLabel(status) {
  return {
    OK: "健康",
    WARN: "预警",
    CRITICAL: "严重异常",
    NO_DATA: "暂无数据",
  }[status] || status;
}

function statusColor(status) {
  return {
    OK: "var(--ok)",
    WARN: "var(--warn)",
    CRITICAL: "var(--critical)",
    NO_DATA: "var(--muted)",
  }[status] || "var(--muted)";
}

function severityLabel(severity) {
  return {
    OK: "健康",
    INFO: "信息",
    WARN: "预警",
    CRITICAL: "严重",
  }[severity] || severity;
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds))) return "--";
  const value = Number(seconds);
  if (value < 60) return `${Math.floor(value)}秒`;
  if (value < 3600) return `${Math.floor(value / 60)}分钟`;
  if (value < 86400) return `${Math.floor(value / 3600)}小时`;
  return `${Math.floor(value / 86400)}天`;
}

function formatRss(rssKb) {
  const value = Number(rssKb);
  if (!Number.isFinite(value)) return "--";
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} GB`;
  return `${(value / 1024).toFixed(1)} MB`;
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`请求失败，状态码 ${response.status}`);
  return response.json();
}

async function loadData() {
  const hours = nodes.rangeSelect.value;
  const page = state.findingsPagination.page || 1;
  const pageSize = state.findingsPagination.page_size || 20;
  const [summary, history, findings] = await Promise.all([
    getJson("/api/summary"),
    getJson(`/api/history?hours=${hours}&limit=2000`),
    getJson(`/api/findings?hours=${hours}&limit=${pageSize}&page=${page}`),
  ]);

  state.summary = summary;
  state.history = history.samples || [];
  state.findings = findings.findings || [];
  state.findingsPagination = findings.pagination || state.findingsPagination;
  render();
}

function render() {
  renderSummary();
  renderChart();
  renderActiveFindings();
  renderFindingsTable();
  renderTopProcesses();
}

function renderSummary() {
  const summary = state.summary || {};
  const latest = summary.latest || {};
  const status = summary.status || "NO_DATA";
  const last24h = summary.last_24h || {};

  nodes.statusDot.style.background = statusColor(status);
  nodes.statusText.textContent = statusLabel(status);
  nodes.lastSample.textContent = formatTime(latest.timestamp);
  nodes.findingCount.textContent = `${last24h.total || 0}`;
  nodes.loadValue.textContent = formatNumber(latest.load_per_cpu, 2);
  nodes.loadMeta.textContent = latest.load_1m === null || latest.load_1m === undefined
    ? "--"
    : `1分钟负载 ${formatNumber(latest.load_1m, 2)} / ${latest.cpu_count || "--"} 核`;
  nodes.temperatureValue.textContent = formatNumber(latest.temperature_celsius, 1, "C");
  nodes.memoryValue.textContent = formatNumber(latest.memory_percent, 1, "%");
  nodes.diskValue.textContent = formatNumber(latest.max_disk_percent, 1, "%");
}

function chartSeries() {
  return [
    { key: "load_per_cpu", color: "#22577a", scale: 40 },
    { key: "temperature_celsius", color: "#c2410c", scale: 100 },
    { key: "memory_percent", color: "#2f855a", scale: 100 },
    { key: "max_disk_percent", color: "#6d5bd0", scale: 100 },
  ];
}

function renderChart() {
  const canvas = nodes.chart;
  const context = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  context.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 18, right: 18, bottom: 28, left: 42 };
  context.clearRect(0, 0, width, height);

  context.strokeStyle = "#d9dfd2";
  context.lineWidth = 1;
  context.font = "12px system-ui";
  context.fillStyle = "#687268";

  for (let step = 0; step <= 4; step += 1) {
    const y = padding.top + ((height - padding.top - padding.bottom) * step) / 4;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
    context.fillText(`${100 - step * 25}%`, 8, y + 4);
  }

  nodes.sampleCount.textContent = `${state.history.length} 条采样`;
  if (state.history.length < 2) {
    context.fillText("暂无足够历史数据", padding.left, height / 2);
    return;
  }

  const firstTs = state.history[0].timestamp;
  const lastTs = state.history[state.history.length - 1].timestamp;
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  for (const series of chartSeries()) {
    context.strokeStyle = series.color;
    context.lineWidth = 2;
    context.beginPath();
    let started = false;

    for (const sample of state.history) {
      const value = sample[series.key];
      if (value === null || value === undefined) {
        started = false;
        continue;
      }
      const x = padding.left + ((sample.timestamp - firstTs) / Math.max(1, lastTs - firstTs)) * plotWidth;
      const normalized = Math.max(0, Math.min(1, Number(value) / series.scale));
      const y = padding.top + (1 - normalized) * plotHeight;
      if (!started) {
        context.moveTo(x, y);
        started = true;
      } else {
        context.lineTo(x, y);
      }
    }
    context.stroke();
  }

  context.fillStyle = "#687268";
  context.fillText(formatTime(firstTs), padding.left, height - 8);
  const endLabel = formatTime(lastTs);
  context.fillText(endLabel, Math.max(padding.left, width - padding.right - context.measureText(endLabel).width), height - 8);
}

function findingMarkup(finding) {
  const severityClass = String(finding.severity || "").toLowerCase();
  const repeatText = repeatLabel(finding);
  return `
    <div class="finding-item ${severityClass}">
      <strong>${severityLabel(finding.severity)} · ${finding.finding_key}</strong>
      <p>${formatFindingTime(finding)}${repeatText} · ${escapeHtml(finding.message)}</p>
    </div>
  `;
}

function renderActiveFindings() {
  const findings = state.summary?.active_findings || [];
  nodes.activeFindings.innerHTML = findings.length
    ? findings.slice(0, 8).map(findingMarkup).join("")
    : '<p class="empty">当前没有活跃异常。</p>';
}

function renderFindingsTable() {
  const pagination = state.findingsPagination || {};
  const total = Number(pagination.total || state.findings.length || 0);
  const page = Number(pagination.page || 1);
  const totalPages = Number(pagination.total_pages || 1);

  nodes.historyFindingCount.textContent = `合并后 ${total} 条`;
  nodes.findingPageState.textContent = `${page} / ${totalPages}`;
  nodes.prevFindingPage.disabled = page <= 1;
  nodes.nextFindingPage.disabled = page >= totalPages;
  nodes.findingsTable.innerHTML = state.findings.length
    ? state.findings.map((finding) => `
      <tr>
        <td>${formatFindingTime(finding)}${repeatLabel(finding)}</td>
        <td><span class="badge ${String(finding.severity).toLowerCase()}">${severityLabel(finding.severity)}</span></td>
        <td>${escapeHtml(finding.finding_key)}</td>
        <td>${escapeHtml(finding.message)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="4" class="empty">所选时间范围内没有异常记录。</td></tr>';
}

function formatFindingTime(finding) {
  const firstTimestamp = finding.first_timestamp || finding.timestamp;
  const lastTimestamp = finding.last_timestamp || finding.timestamp;
  if (firstTimestamp && lastTimestamp && firstTimestamp !== lastTimestamp) {
    return `${formatTime(firstTimestamp)} - ${formatTime(lastTimestamp)}`;
  }
  return formatTime(lastTimestamp || firstTimestamp);
}

function repeatLabel(finding) {
  const repeatCount = Number(finding.repeat_count || 1);
  return repeatCount > 1 ? ` · 重复 ${repeatCount} 次` : "";
}

function renderTopProcesses() {
  const topProcesses = state.summary?.top_processes || {};
  renderProcessList(nodes.topCpuList, nodes.topCpuTime, topProcesses.cpu || [], "cpu");
  renderProcessList(nodes.topMemoryList, nodes.topMemoryTime, topProcesses.memory || [], "memory");
}

function renderProcessList(container, timeNode, processes, rankType) {
  if (!container || !timeNode) return;
  const latestTimestamp = processes[0]?.timestamp;
  timeNode.textContent = latestTimestamp ? `采样 ${formatTime(latestTimestamp)}` : "--";
  container.innerHTML = processes.length
    ? processes.map((process) => processMarkup(process, rankType)).join("")
    : '<p class="empty">暂无进程采样数据。</p>';
}

function processMarkup(process, rankType) {
  const primaryPercent = rankType === "memory" ? process.memory_percent : process.cpu_percent;
  const meterWidth = Math.max(1, Math.min(100, Number(primaryPercent) || 0));
  const meterClass = rankType === "memory" ? "process-meter memory" : "process-meter";
  return `
    <div class="process-row">
      <div class="process-main">
        <strong>#${process.rank_position} · PID ${process.pid}</strong>
        <code title="${escapeHtml(process.command)}">${escapeHtml(process.command)}</code>
      </div>
      <div class="process-stats">
        <span>CPU ${formatNumber(process.cpu_percent, 1, "%")} · 内存 ${formatNumber(process.memory_percent, 1, "%")}</span>
        <span>RSS ${formatRss(process.rss_kb)} · 运行 ${formatDuration(process.elapsed_seconds)}</span>
        <div class="${meterClass}"><span style="width: ${meterWidth}%"></span></div>
      </div>
    </div>
  `;
}

function setupAutoRefresh() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  if (state.countdownTimer) clearInterval(state.countdownTimer);

  const intervalSeconds = Number(nodes.refreshSelect.value);
  if (!intervalSeconds) {
    state.nextRefreshAt = null;
    nodes.refreshState.textContent = "自动刷新已关闭";
    return;
  }

  state.nextRefreshAt = Date.now() + intervalSeconds * 1000;
  state.refreshTimer = setInterval(() => {
    loadData().catch(() => undefined);
    state.nextRefreshAt = Date.now() + intervalSeconds * 1000;
  }, intervalSeconds * 1000);
  state.countdownTimer = setInterval(renderRefreshState, 1000);
  renderRefreshState();
}

function renderRefreshState() {
  if (!state.nextRefreshAt) return;
  const remainingSeconds = Math.max(0, Math.ceil((state.nextRefreshAt - Date.now()) / 1000));
  nodes.refreshState.textContent = `${remainingSeconds} 秒后刷新`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

nodes.refreshButton.addEventListener("click", () => {
  loadData().catch((error) => {
    nodes.statusText.textContent = `加载失败: ${error.message}`;
    nodes.statusDot.style.background = "var(--critical)";
  });
  setupAutoRefresh();
});

nodes.rangeSelect.addEventListener("change", () => {
  state.findingsPagination.page = 1;
  loadData().catch((error) => {
    nodes.statusText.textContent = `加载失败: ${error.message}`;
    nodes.statusDot.style.background = "var(--critical)";
  });
  setupAutoRefresh();
});

nodes.refreshSelect.addEventListener("change", () => {
  setupAutoRefresh();
});

nodes.prevFindingPage.addEventListener("click", () => {
  state.findingsPagination.page = Math.max(1, Number(state.findingsPagination.page || 1) - 1);
  loadData().catch((error) => {
    nodes.statusText.textContent = `加载失败: ${error.message}`;
    nodes.statusDot.style.background = "var(--critical)";
  });
});

nodes.nextFindingPage.addEventListener("click", () => {
  const totalPages = Number(state.findingsPagination.total_pages || 1);
  state.findingsPagination.page = Math.min(totalPages, Number(state.findingsPagination.page || 1) + 1);
  loadData().catch((error) => {
    nodes.statusText.textContent = `加载失败: ${error.message}`;
    nodes.statusDot.style.background = "var(--critical)";
  });
});

window.addEventListener("resize", () => renderChart());

loadData().catch((error) => {
  nodes.statusText.textContent = `加载失败: ${error.message}`;
  nodes.statusDot.style.background = "var(--critical)";
});
setupAutoRefresh();
