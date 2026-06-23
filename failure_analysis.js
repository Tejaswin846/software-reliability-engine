const statusEl = document.getElementById("analysis-status");

function text(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function pct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function seconds(value) {
  return `${Number(value || 0).toFixed(2)}s`;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function emptyRow(message, columns = 5) {
  return `<tr><td colspan="${columns}" class="muted">${message}</td></tr>`;
}

function renderBars(containerId, items, valueKey = "count", labelKey = "label") {
  const container = document.getElementById(containerId);
  if (!container) {
    return;
  }
  if (!items.length) {
    container.innerHTML = `<div class="empty">No failure causes recorded yet.</div>`;
    return;
  }
  const max = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
  container.innerHTML = items
    .map((item) => {
      const value = Number(item[valueKey] || 0);
      const width = Math.max(2, (value / max) * 100);
      const detail = item.percentage !== undefined ? `${value} (${pct(item.percentage)})` : `${value}`;
      return `
        <div class="bar-row">
          <div class="bar-label">
            <strong>${item[labelKey]}</strong>
            <span>${detail}</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill danger" style="width:${width}%"></div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderTrendChart(trends) {
  const container = document.getElementById("failure-trend-chart");
  if (!container) {
    return;
  }
  if (!trends.length) {
    container.innerHTML = `<div class="empty">No trend data yet.</div>`;
    return;
  }
  const width = 720;
  const height = 220;
  const padding = 34;
  const max = Math.max(...trends.map((point) => Number(point.failures || 0)), 1);
  const barGap = 8;
  const barWidth = Math.max(10, (width - padding * 2 - barGap * (trends.length - 1)) / trends.length);
  const bars = trends
    .map((point, index) => {
      const value = Number(point.failures || 0);
      const barHeight = ((height - padding * 2) * value) / max;
      const x = padding + index * (barWidth + barGap);
      const y = height - padding - barHeight;
      return `
        <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="4" fill="#b42318"></rect>
        <text x="${x + barWidth / 2}" y="${height - 10}" text-anchor="middle" class="chart-label">${point.date.slice(5)}</text>
        <text x="${x + barWidth / 2}" y="${Math.max(16, y - 6)}" text-anchor="middle" class="chart-label">${value}</text>
      `;
    })
    .join("");
  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Failure frequency over time">
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" class="chart-axis"></line>
      ${bars}
    </svg>
  `;
}

function renderRecommendations(recommendations) {
  const container = document.getElementById("recommendations");
  if (!container) {
    return;
  }
  if (!recommendations.length) {
    container.innerHTML = `<div class="empty">No recommendations yet.</div>`;
    return;
  }
  container.innerHTML = recommendations
    .map(
      (item) => `
        <article class="recommendation-card">
          <span class="category-chip">Recommendation</span>
          <h3>${item.issue}</h3>
          <p>${item.recommendation}</p>
          <strong>Expected improvement: ${pct(item.expected_improvement)}</strong>
        </article>
      `,
    )
    .join("");
}

function renderUnstableWorkflows(workflows) {
  const tbody = document.getElementById("unstable-workflows");
  if (!tbody) {
    return;
  }
  if (!workflows.length) {
    tbody.innerHTML = emptyRow("No unstable workflows found.");
    return;
  }
  tbody.innerHTML = workflows
    .map(
      (workflow) => `
        <tr>
          <td class="model-name">${workflow.workflow_name}</td>
          <td>${workflow.failure_count}</td>
          <td>${seconds(workflow.average_duration)}</td>
          <td>${Number(workflow.average_retries || 0).toFixed(2)}</td>
          <td><span class="score-chip">${Number(workflow.impact || 0).toFixed(2)}</span></td>
        </tr>
      `,
    )
    .join("");
}

function renderFailedWorkflows(workflows) {
  const tbody = document.getElementById("failed-workflows-table");
  if (!tbody) {
    return;
  }
  if (!workflows.length) {
    tbody.innerHTML = emptyRow("No failed workflow records found.", 6);
    return;
  }
  tbody.innerHTML = workflows
    .map((workflow) => {
      const timestamp = workflow.timestamp ? new Date(workflow.timestamp).toLocaleString() : "--";
      return `
        <tr>
          <td>${timestamp}</td>
          <td class="model-name">${workflow.workflow_id}</td>
          <td>${workflow.failure_reason}</td>
          <td>${seconds(workflow.execution_duration)}</td>
          <td>${workflow.retry_count}</td>
          <td>${workflow.source}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadFailureAnalysis() {
  try {
    const response = await fetch("/api/failure-analysis");
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const data = await response.json();
    const summary = data.summary || {};
    text("total-workflows", summary.total_workflows || 0);
    text("failed-workflows", summary.failed_workflows || 0);
    text("failure-rate", pct(summary.failure_rate));
    text("avg-duration", seconds(summary.average_execution_duration));
    text("impact-score", Number(summary.reliability_impact_score || 0).toFixed(2));
    text("analysis-updated", `Updated ${new Date().toLocaleString()}`);
    renderBars("failure-causes", data.top_failure_causes || []);
    renderTrendChart(data.failure_trends || []);
    renderRecommendations(data.recommendations || []);
    renderUnstableWorkflows(data.unstable_workflows || []);
    renderFailedWorkflows(data.failed_workflows || []);
    setStatus("Failure analysis ready");
  } catch (error) {
    console.error(error);
    setStatus("Failed to load failure analysis", true);
  }
}

loadFailureAnalysis();
