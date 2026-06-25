const statusEl = document.getElementById("dashboard-status");

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const element = byId(id);
  if (element) {
    element.textContent = value;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatDecimal(value, digits = 2) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercent(value) {
  return `${formatDecimal(value, 2)}%`;
}

function formatConfidence(value) {
  const numeric = Number(value || 0);
  const percent = numeric <= 1 ? numeric * 100 : numeric;
  return `${formatDecimal(percent, 1)}%`;
}

function formatLatency(ms) {
  const numeric = Number(ms || 0);
  if (numeric >= 1000) {
    return `${formatDecimal(numeric / 1000, 2)}s`;
  }
  return `${formatDecimal(numeric, 0)}ms`;
}

function formatCurrencyMinorUnits(amount, currency) {
  const normalizedCurrency = String(currency || "usd").toUpperCase();
  const major = Number(amount || 0) / 100;
  return `${normalizedCurrency} ${formatDecimal(major, 2)}`;
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function emptyMarkup(message) {
  return `<div class="empty">${escapeHtml(message)}</div>`;
}

function barMarkup(value, maxValue = 100, kind = "") {
  const numeric = Math.max(0, Number(value || 0));
  const max = Math.max(1, Number(maxValue || 100));
  const width = Math.min(100, (numeric / max) * 100);
  const className = kind ? `bar-fill ${kind}` : "bar-fill";
  return `
    <div class="bar-track">
      <div class="${className}" style="width: ${width}%"></div>
    </div>
  `;
}

function renderOverview(overview) {
  setText("total-runs", formatNumber(overview.total_benchmark_runs));
  setText("total-workflows", formatNumber(overview.total_workflows));
  setText("success-rate", formatPercent(overview.success_rate));
  setText("failure-rate", formatPercent(overview.failure_rate));
  setText("reliability-score", formatDecimal(overview.reliability_score, 2));
  setText("last-updated", `Last updated: ${formatDate(overview.last_updated)}`);
}

function renderRedis(redis) {
  const status = redis?.status || "Not configured";
  const connected = Boolean(redis?.connected);
  setText("redis-status", status);
  setText("redis-latency", connected ? formatLatency(redis.latency_ms) : "--");
  setText("redis-cache-hits", formatNumber(redis?.cache_hits));
  setText("redis-cache-misses", formatNumber(redis?.cache_misses));
  setText("redis-memory", redis?.memory_usage || "Unavailable");
  setText("redis-queue-depth", formatNumber(redis?.queue_depth));
  setText("redis-hit-rate", formatPercent(redis?.cache_hit_rate));
  const dot = byId("redis-status-dot");
  if (dot) {
    dot.classList.toggle("connected", connected);
  }
}

function formatQuota(value) {
  return value === null || value === undefined ? "Unlimited" : formatNumber(value);
}

function renderBilling(billing) {
  const invoiceList = byId("billing-invoice-list");
  if (!billing || !billing.plan) {
    setText("billing-plan", "--");
    setText("billing-workflows", "--");
    setText("billing-remaining", "--");
    setText("billing-api-requests", "--");
    setText("billing-stripe-status", "--");
    setText("billing-invoices", "--");
    setText("billing-note", "Login to see project-scoped plan and usage data.");
    if (invoiceList) {
      invoiceList.innerHTML = emptyMarkup("Login to view invoices.");
    }
    return;
  }
  const workflowLimit = formatQuota(billing.plan.monthly_workflow_limit);
  const workflowUsed = formatNumber(billing.usage.workflows);
  const invoices = billing.invoices || [];
  const stripeStatus = billing.stripe?.status || billing.subscription?.stripe_status || (billing.stripe?.configured ? "Configured" : "Not configured");
  setText("billing-plan", billing.plan.name);
  setText("billing-workflows", `${workflowUsed} / ${workflowLimit}`);
  setText("billing-remaining", formatQuota(billing.remaining.workflows));
  setText("billing-api-requests", formatNumber(billing.usage.api_requests));
  setText("billing-stripe-status", stripeStatus);
  setText("billing-invoices", formatNumber(invoices.length));
  setText(
    "billing-note",
    `${formatNumber(billing.usage.projects)} projects, ${formatNumber(billing.usage.api_keys)} active API keys this period.`
  );
  if (invoiceList) {
    invoiceList.innerHTML = invoices.length
      ? invoices.map((invoice) => `
          <div class="bar-row">
            <div class="bar-label">
              <strong>${escapeHtml(invoice.status || "invoice")}</strong>
              <span>${escapeHtml(formatDate(invoice.created_at))}</span>
            </div>
            <div class="muted">
              Paid ${escapeHtml(formatCurrencyMinorUnits(invoice.amount_paid, invoice.currency))}
              ${invoice.hosted_invoice_url ? ` | <a class="small-link" href="${escapeHtml(invoice.hosted_invoice_url)}" target="_blank" rel="noopener">View invoice</a>` : ""}
            </div>
          </div>
        `).join("")
      : emptyMarkup("No invoices yet.");
  }
}

async function billingPost(endpoint, payload = {}) {
  const response = await fetch(endpoint, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Billing API returned ${response.status}`);
  }
  return data;
}

function setBillingBusy(isBusy) {
  const upgrade = byId("billing-upgrade-pro");
  const portal = byId("billing-portal");
  if (upgrade) {
    upgrade.disabled = isBusy;
  }
  if (portal) {
    portal.disabled = isBusy;
  }
}

function wireBillingActions() {
  const upgrade = byId("billing-upgrade-pro");
  const portal = byId("billing-portal");
  if (upgrade) {
    upgrade.addEventListener("click", async () => {
      try {
        setBillingBusy(true);
        setText("billing-note", "Creating Stripe checkout session...");
        const data = await billingPost("/api/billing/checkout", { plan_id: "pro" });
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
          return;
        }
        setText("billing-note", data.message || "Billing plan updated.");
        loadDashboard();
      } catch (error) {
        setText("billing-note", error.message);
      } finally {
        setBillingBusy(false);
      }
    });
  }
  if (portal) {
    portal.addEventListener("click", async () => {
      try {
        setBillingBusy(true);
        setText("billing-note", "Opening Stripe billing portal...");
        const data = await billingPost("/api/billing/portal", {});
        if (data.portal_url) {
          window.location.href = data.portal_url;
          return;
        }
        setText("billing-note", "Stripe did not return a billing portal URL.");
      } catch (error) {
        setText("billing-note", error.message);
      } finally {
        setBillingBusy(false);
      }
    });
  }
}

function renderTeamWorkspaces(team) {
  const organizations = team.organizations || [];
  const members = team.members || [];
  const invitations = team.invitations || [];
  setText("team-org-count", formatNumber(team.organization_count));
  setText("team-member-count", formatNumber(team.member_count));
  setText("team-invite-count", formatNumber(team.pending_invitation_count));

  const orgList = byId("team-orgs");
  if (orgList) {
    orgList.innerHTML = organizations.length
      ? organizations.map((org) => `
          <div class="bar-row">
            <div class="bar-label">
              <strong>${escapeHtml(org.name)}</strong>
              <span>${escapeHtml(org.role)}</span>
            </div>
            <div class="muted">${formatNumber(org.member_count)} members | ${formatNumber(org.invitation_count)} pending invites</div>
          </div>
        `).join("")
      : emptyMarkup("No organizations yet.");
  }

  const inviteList = byId("team-invitations");
  if (inviteList) {
    inviteList.innerHTML = invitations.length
      ? invitations.slice(0, 6).map((invite) => `
          <div class="bar-row">
            <div class="bar-label">
              <strong>${escapeHtml(invite.email)}</strong>
              <span>${escapeHtml(invite.status)}</span>
            </div>
            <div class="muted">${escapeHtml(invite.organization_name || invite.organization_id)} | ${escapeHtml(invite.role)}</div>
          </div>
        `).join("")
      : emptyMarkup("No invitations yet.");
  }

  const table = byId("team-members-table");
  if (table) {
    table.innerHTML = members.length
      ? members.map((member) => `
          <tr>
            <td>${escapeHtml(member.organization_name || member.organization_id)}</td>
            <td>${escapeHtml(member.email)}</td>
            <td><span class="category-chip">${escapeHtml(member.role)}</span></td>
            <td>${formatDate(member.created_at)}</td>
          </tr>
        `).join("")
      : `<tr><td colspan="4">No team members found.</td></tr>`;
  }
}

function renderModelLeaderboard(models) {
  const table = byId("model-table");
  if (!models.length) {
    table.innerHTML = `<tr><td colspan="6">No model benchmark rows found.</td></tr>`;
    return;
  }

  table.innerHTML = models.map((model) => `
    <tr>
      <td>${formatNumber(model.rank)}</td>
      <td class="model-name">${escapeHtml(model.model)}</td>
      <td><span class="score-chip">${formatDecimal(model.reliability_score_v2, 2)}</span></td>
      <td>${formatPercent(model.success_rate)}</td>
      <td>${formatLatency(model.average_execution_time_ms)}</td>
      <td>${formatConfidence(model.average_confidence)}</td>
    </tr>
  `).join("");
}

function renderToolReliability(tools) {
  const grid = byId("tool-grid");
  if (!tools.length) {
    grid.innerHTML = emptyMarkup("No tool reliability rows found.");
    return;
  }

  grid.innerHTML = tools.map((tool) => `
    <article class="tool-card">
      <header>
        <span class="tool-name">${escapeHtml(tool.tool_name)}</span>
        <span class="score-chip">${formatDecimal(tool.reliability_score, 2)}</span>
      </header>
      <div class="mini-stats">
        <div><span>Success</span><strong>${formatPercent(tool.success_rate)}</strong></div>
        <div><span>Failure</span><strong>${formatPercent(tool.failure_rate)}</strong></div>
        <div><span>Latency</span><strong>${formatLatency(tool.average_latency_ms)}</strong></div>
        <div><span>Timeout</span><strong>${formatPercent(tool.timeout_rate)}</strong></div>
      </div>
    </article>
  `).join("");
}

function renderWorkflowAnalytics(workflow) {
  const stages = workflow.stage_summary || [];
  setText(
    "workflow-summary",
    `${formatNumber(workflow.successful_workflows)} of ${formatNumber(workflow.total_workflows)} workflows completed`
  );

  const failureList = byId("stage-failures");
  const latencyList = byId("stage-latency");
  if (!stages.length) {
    failureList.innerHTML = emptyMarkup("No stage failure metrics found.");
    latencyList.innerHTML = emptyMarkup("No stage latency metrics found.");
  } else {
    failureList.innerHTML = stages.map((stage) => `
      <div class="bar-row">
        <div class="bar-label">
          <strong>${escapeHtml(stage.stage)}</strong>
          <span>${formatPercent(stage.failure_rate)} failures</span>
        </div>
        ${barMarkup(stage.failure_rate, 100, stage.failure_rate > 0 ? "danger" : "")}
      </div>
    `).join("");

    const maxLatency = Math.max(...stages.map((stage) => Number(stage.average_latency_ms || 0)), 1);
    latencyList.innerHTML = stages.map((stage) => `
      <div class="bar-row">
        <div class="bar-label">
          <strong>${escapeHtml(stage.stage)}</strong>
          <span>${formatLatency(stage.average_latency_ms)}</span>
        </div>
        ${barMarkup(stage.average_latency_ms, maxLatency, "warning")}
      </div>
    `).join("");
  }

  const dropList = byId("confidence-drops");
  const drops = workflow.confidence_drops || [];
  if (!drops.length) {
    dropList.innerHTML = emptyMarkup("No confidence drops found.");
    return;
  }

  dropList.innerHTML = drops.map((drop) => {
    const value = Number(drop.drop || 0);
    const sign = value > 0 ? "-" : "+";
    const display = `${sign}${formatDecimal(Math.abs(value) * 100, 1)} pts`;
    return `
      <div class="drop-row">
        <span class="drop-route">${escapeHtml(drop.from_stage)} to ${escapeHtml(drop.to_stage)}</span>
        <span class="drop-value">${display}</span>
      </div>
    `;
  }).join("");
}

function renderPredictionAnalytics(prediction) {
  setText("prediction-accuracy", formatPercent(prediction.accuracy));
  setText("prediction-precision", formatPercent(prediction.precision));
  setText("prediction-recall", formatPercent(prediction.recall));
  setText("prediction-fp", formatNumber(prediction.false_positives));
  setText("prediction-fn", formatNumber(prediction.false_negatives));
}

function renderGuardrailAnalytics(guardrails) {
  setText("guardrail-interventions", formatNumber(guardrails.interventions));
  setText("guardrail-prevented", formatNumber(guardrails.prevented_failures));
  setText("guardrail-recovery", formatPercent(guardrails.recovery_success_rate));
  setText("guardrail-latency", formatLatency(guardrails.recovery_latency_ms));
}

function renderRecoveryAnalytics(recovery) {
  setText("recovery-today", formatNumber(recovery.recoveries_today));
  setText("recovery-success", formatPercent(recovery.recovery_success_rate));
  setText("recovery-latency", formatLatency(recovery.average_recovery_latency_ms));
  const list = byId("recovery-categories");
  const categories = recovery.top_failure_categories || [];
  if (!list) {
    return;
  }
  if (!categories.length) {
    list.innerHTML = emptyMarkup("No auto-recovery attempts yet.");
    return;
  }
  const maxCount = Math.max(...categories.map((category) => Number(category.count || 0)), 1);
  list.innerHTML = categories.map((category) => `
    <div class="bar-row">
      <div class="bar-label">
        <strong>${escapeHtml(category.failure_category)}</strong>
        <span>${formatNumber(category.count)}</span>
      </div>
      ${barMarkup(category.count, maxCount, "warning")}
    </div>
  `).join("");
}

function renderCopilot(copilot) {
  const summary = copilot.summary || {};
  const recommendations = copilot.recommendations || [];
  setText("copilot-count", formatNumber(summary.recommendation_count));
  setText("copilot-confidence", formatPercent(summary.average_confidence));
  setText("copilot-improvement", formatPercent(summary.total_estimated_success_improvement));

  const table = byId("copilot-table");
  if (!table) {
    return;
  }
  if (!recommendations.length) {
    table.innerHTML = `<tr><td colspan="5">No Copilot recommendations found.</td></tr>`;
    return;
  }

  table.innerHTML = recommendations.map((item) => {
    const evidence = (item.supporting_evidence || [])
      .slice(0, 2)
      .map((entry) => `<span class="evidence-line">${escapeHtml(entry)}</span>`)
      .join("");
    return `
      <tr>
        <td>
          <span class="category-chip">${escapeHtml(item.category)}</span>
          <div class="recommendation-issue">${escapeHtml(item.issue)}</div>
        </td>
        <td>${escapeHtml(item.recommendation)}</td>
        <td>${formatPercent(item.estimated_success_improvement)}</td>
        <td>${formatPercent(item.confidence)}</td>
        <td>${evidence || "--"}</td>
      </tr>
    `;
  }).join("");
}

function renderOptimizer(optimizer) {
  const history = optimizer.history || [];
  setText("optimizer-actions", formatNumber(optimizer.autonomous_actions));
  setText("optimizer-improvement", formatPercent(optimizer.estimated_success_improvement));
  setText("optimizer-rollbacks", formatNumber(optimizer.rollbacks));
  setText("optimizer-dryruns", formatNumber(optimizer.dry_runs));
  setText("optimizer-applied", formatNumber(optimizer.applied_actions));
  setText("optimizer-confidence", formatPercent(optimizer.average_confidence));

  const table = byId("optimizer-history-table");
  if (!table) {
    return;
  }
  if (!history.length) {
    table.innerHTML = `<tr><td colspan="6">No autonomous optimization actions yet.</td></tr>`;
    return;
  }
  table.innerHTML = history.map((event) => `
    <tr>
      <td><span class="category-chip">${escapeHtml(event.action_type)}</span></td>
      <td>${escapeHtml(event.target)}</td>
      <td>${escapeHtml(event.status)}</td>
      <td>${formatPercent(event.estimated_success_improvement)}</td>
      <td>${formatPercent(event.confidence)}</td>
      <td>${formatDate(event.created_at)}</td>
    </tr>
  `).join("");
}

function renderMetaReliability(meta) {
  const decisions = meta.recent_decisions || [];
  const rejected = meta.rejected_actions || [];
  setText("meta-decisions", formatNumber(meta.total_decisions));
  setText("meta-pending", formatNumber(meta.pending_human));
  setText("meta-rejected", formatNumber(meta.rejected_unsafe));
  setText("meta-approved", formatNumber(meta.approved));
  setText("meta-high-risk", formatNumber(meta.high_risk));

  const table = byId("meta-decision-table");
  if (table) {
    if (!decisions.length) {
      table.innerHTML = `<tr><td colspan="5">No AI decisions have been validated yet.</td></tr>`;
    } else {
      table.innerHTML = decisions.map((decision) => `
        <tr>
          <td>
            <span class="category-chip">${escapeHtml(decision.action_type)}</span>
            <div class="evidence-line">${escapeHtml(decision.target)}</div>
          </td>
          <td>${escapeHtml(decision.risk_level)}</td>
          <td>${escapeHtml(decision.status)}</td>
          <td>${formatPercent(decision.confidence)}</td>
          <td>${formatDate(decision.created_at)}</td>
        </tr>
      `).join("");
    }
  }

  const rejectedList = byId("meta-rejected-list");
  if (!rejectedList) {
    return;
  }
  if (!rejected.length) {
    rejectedList.innerHTML = emptyMarkup("No unsafe AI actions rejected yet.");
    return;
  }
  rejectedList.innerHTML = rejected.map((decision) => `
    <div class="bar-row">
      <div class="bar-label">
        <strong>${escapeHtml(decision.action_type)}</strong>
        <span>${escapeHtml(decision.risk_level)}</span>
      </div>
      <div class="muted">${escapeHtml(decision.target)} | ${escapeHtml(decision.status)}</div>
    </div>
  `).join("");
}

function renderHistoricalTrends(trends) {
  const list = byId("trend-list");
  if (!trends.length) {
    list.innerHTML = emptyMarkup("No historical trend rows found.");
    return;
  }

  list.innerHTML = trends.map((trend) => `
    <div class="trend-row">
      <div class="trend-label">
        <strong>${escapeHtml(trend.label)}</strong>
        <span>${formatDate(trend.created_at)}</span>
      </div>
      <div class="bar-label">
        <span>Reliability ${formatDecimal(trend.reliability_score, 2)}</span>
        <span>Success ${formatPercent(trend.success_rate)} | Failure ${formatPercent(trend.failure_rate)}</span>
      </div>
      ${barMarkup(trend.reliability_score, 100)}
    </div>
  `).join("");
}

function renderSdkWorkflows(sdk) {
  setText("sdk-total", formatNumber(sdk.total_workflows));
  setText("sdk-success", formatPercent(sdk.success_rate));
  setText("sdk-latency", formatLatency(sdk.average_latency_ms));

  const table = byId("sdk-workflow-table");
  const workflows = sdk.recent_workflows || [];
  if (!workflows.length) {
    table.innerHTML = `<tr><td colspan="7">No SDK-submitted workflows yet.</td></tr>`;
    return;
  }

  table.innerHTML = workflows.map((workflow) => {
    const success = workflow.success === 1 ? "Yes" : workflow.success === 0 ? "No" : "--";
    const risk = workflow.predicted_failure_probability === null || workflow.predicted_failure_probability === undefined
      ? "--"
      : formatPercent(Number(workflow.predicted_failure_probability) * 100);
    return `
      <tr>
        <td class="model-name">${escapeHtml(workflow.project_name)}</td>
        <td>${escapeHtml(workflow.workflow_name)}</td>
        <td>${escapeHtml(workflow.status)}</td>
        <td>${success}</td>
        <td>${risk}</td>
        <td>${escapeHtml(workflow.guardrail_action || "--")}</td>
        <td>${formatLatency(workflow.total_latency_ms)}</td>
      </tr>
    `;
  }).join("");
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/me/dashboard", {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
    });
    if (!response.ok) {
      throw new Error(`Dashboard API returned ${response.status}`);
    }
    const payload = await response.json();
    renderOverview(payload.overview || {});
    renderRedis(payload.redis || {});
    renderTeamWorkspaces(payload.team_workspaces || {});
    renderModelLeaderboard(payload.model_leaderboard || []);
    renderToolReliability(payload.tool_reliability || []);
    renderWorkflowAnalytics(payload.workflow_analytics || {});
    renderPredictionAnalytics(payload.prediction_analytics || {});
    renderGuardrailAnalytics(payload.guardrail_analytics || {});
    renderRecoveryAnalytics(payload.recovery_analytics || {});
    renderCopilot(payload.copilot || {});
    renderOptimizer(payload.optimizer || {});
    renderMetaReliability(payload.meta_reliability || {});
    renderHistoricalTrends(payload.historical_trends || []);
    renderBilling(payload.billing || null);
    renderSdkWorkflows(payload.sdk_workflows || {});
    statusEl.textContent = "Project-scoped data loaded";
    statusEl.classList.remove("error");
  } catch (error) {
    statusEl.textContent = `Dashboard error: ${error.message}`;
    statusEl.classList.add("error");
  }
}

wireBillingActions();
loadDashboard();
