async function api(path, options = {}) {
  return window.SoftwareAuth.request(path, options);
}

function showMessage(id, text, kind = "success") {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }
  element.textContent = text;
  element.className = `message visible ${kind}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function requireSession() {
  try {
    const response = await window.SoftwareAuth.session();
    const userLabel = document.getElementById("user-label");
    if (userLabel) {
      userLabel.textContent = response.user.email;
    }
    return response.user;
  } catch (_) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
    return null;
  }
}

function wireLogout() {
  window.SoftwareAuth.wireLogout();
}

function initLogin() {
  const form = document.getElementById("login-form");
  if (!form) {
    return;
  }
  const query = new URLSearchParams(window.location.search);
  if (query.get("confirmed") === "1") {
    showMessage("login-message", "Email confirmed. You can sign in now.", "success");
  } else if (query.get("reset") === "1") {
    showMessage("login-message", "Password updated. Sign in with your new password.", "success");
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      email: form.email.value,
      password: form.password.value,
    };
    try {
      const response = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const requestedNext = new URLSearchParams(window.location.search).get("next");
      const next = requestedNext && requestedNext.startsWith("/") ? requestedNext : "/projects";
      window.location.href = next;
    } catch (error) {
      showMessage("login-message", error.message, "error");
    }
  });
}

function initRegister() {
  const form = document.getElementById("register-form");
  if (!form) {
    return;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      email: form.email.value,
      password: form.password.value,
    };
    try {
      const response = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (response.confirmation_required) {
        showMessage(
          "register-message",
          "Account created. Check your email to confirm the account, then log in.",
          "success",
        );
        form.reset();
        return;
      }
      window.location.href = "/projects";
    } catch (error) {
      showMessage("register-message", error.message, "error");
    }
  });
}

function initPasswordResetRequest() {
  const form = document.getElementById("forgot-password-form");
  if (!form) {
    return;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const response = await api("/auth/password-reset", {
        method: "POST",
        body: JSON.stringify({ email: form.email.value }),
      });
      showMessage("forgot-password-message", response.message, "success");
      form.reset();
    } catch (error) {
      showMessage("forgot-password-message", error.message, "error");
    }
  });
}

function recoveryTokens() {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return {
    access_token: hash.get("access_token"),
    refresh_token: hash.get("refresh_token"),
  };
}

function initPasswordUpdate() {
  const form = document.getElementById("reset-password-form");
  if (!form) {
    return;
  }
  const tokens = recoveryTokens();
  if (!tokens.access_token || !tokens.refresh_token) {
    showMessage(
      "reset-password-message",
      "Open this page from the password reset link sent by Supabase.",
      "error",
    );
    form.querySelector("button").disabled = true;
    return;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form.password.value !== form.confirm_password.value) {
      showMessage("reset-password-message", "Passwords do not match.", "error");
      return;
    }
    try {
      const response = await api("/auth/password-update", {
        method: "POST",
        body: JSON.stringify({
          ...tokens,
          password: form.password.value,
        }),
      });
      showMessage("reset-password-message", response.message, "success");
      window.setTimeout(() => {
        window.location.href = "/login?reset=1";
      }, 900);
    } catch (error) {
      showMessage("reset-password-message", error.message, "error");
    }
  });
}

function formatProjectDate(value) {
  if (!value) return "No activity yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 90) return "Now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return date.toLocaleDateString();
}

async function loadProjects() {
  const list = document.getElementById("project-list");
  const select = document.getElementById("project-select");
  const currentSelect = document.getElementById("current-project-select");
  if (!list && !select && !currentSelect) return;
  const response = await api("/api/projects");
  if (list) {
    list.innerHTML = response.projects.length ? response.projects.map((project) => `
      <article class="project-card ${project.is_current ? "current" : ""} ${project.status === "archived" ? "archived" : ""}">
        <header><div><span class="status-badge status-${escapeHtml(project.status)}"><i></i>${escapeHtml(project.status)}</span><h2><a href="/projects/${encodeURIComponent(project.id)}">${escapeHtml(project.name)}</a></h2></div>${project.is_current ? '<span class="current-chip">Current</span>' : ""}</header>
        <code>${escapeHtml(project.id)}</code>
        <dl class="project-facts">
          <div><dt>Device</dt><dd>${escapeHtml(project.device_label || "No installation")}</dd></div><div><dt>Environment</dt><dd>${escapeHtml(project.environment || "Development")}</dd></div>
          <div><dt>Workflows</dt><dd>${Number(project.workflow_count || 0).toLocaleString()}</dd></div><div><dt>Reliability</dt><dd>${Number(project.reliability_score || 0).toFixed(1)}%</dd></div>
          <div><dt>Last activity</dt><dd>${formatProjectDate(project.last_activity_at)}</dd></div><div><dt>Installations</dt><dd>${Number(project.connected_installation_count || 0)} connected</dd></div>
          <div><dt>Created</dt><dd>${formatProjectDate(project.created_at)}</dd></div>
        </dl>
        <footer><a class="button secondary" href="/projects/${encodeURIComponent(project.id)}">View details</a><button class="secondary" data-copy-value="${escapeHtml(project.id)}">Copy Project ID</button>${project.status !== "archived" ? `<button class="secondary" data-select-project="${escapeHtml(project.id)}">Make current</button><button class="secondary" data-archive-project="${escapeHtml(project.id)}">Archive</button>` : `<button class="secondary" data-unarchive-project="${escapeHtml(project.id)}">Restore</button>`}<button class="danger" data-delete-project="${escapeHtml(project.id)}">Delete</button></footer>
      </article>`).join("") : `<div class="empty-state"><h2>You haven't connected any projects yet.</h2><p>Create a project above or open Setup to connect your application.</p><a class="button" href="/onboarding">Open setup</a></div>`;
    const count = document.getElementById("project-count");
    if (count) count.textContent = `${response.projects.length} project${response.projects.length === 1 ? "" : "s"}`;
  }
  if (currentSelect) {
    const selectable = response.projects.filter((project) => project.status !== "archived");
    currentSelect.innerHTML = selectable.length ? selectable.map((project) => `<option value="${escapeHtml(project.id)}" ${project.is_current ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("") : '<option value="">No projects</option>';
    const current = response.current_project;
    document.getElementById("current-project-name").textContent = current?.name || "No project selected";
    document.getElementById("current-project-meta").textContent = current ? `${String(current.status).toUpperCase()} · ${current.device_label || "No installation"} · ${current.environment || "Development"}` : "Create or connect a project to begin.";
  }
  if (select) {
    const activeProjects = response.projects.filter((project) => project.status !== "archived");
    const hasProjects = activeProjects.length > 0;
    select.innerHTML = hasProjects ? activeProjects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("") : '<option value="">Create a project first</option>';
    ["create-key-button", "regenerate-key-button"].forEach((id) => { const button = document.getElementById(id); if (button) button.disabled = !hasProjects; });
    const help = document.getElementById("empty-project-help"); if (help) help.hidden = hasProjects;
    const selected = new URLSearchParams(window.location.search).get("project"); if (selected) select.value = selected;
    updateManualProjectId(); await loadApiKeys();
  }
}

function initProjects() {
  const form = document.getElementById("project-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/projects", { method: "POST", body: JSON.stringify({ name: form.name.value, environment: form.environment?.value || "development" }) });
      form.reset(); showMessage("project-message", "Project created.", "success"); await loadProjects();
    } catch (error) { showMessage("project-message", error.message, "error"); }
  });
  document.getElementById("current-project-select")?.addEventListener("change", async (event) => {
    if (!event.target.value) return;
    try { await api("/api/projects/current", { method: "POST", body: JSON.stringify({ project_id: event.target.value }) }); await loadProjects(); }
    catch (error) { showMessage("project-message", error.message, "error"); }
  });
  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-value]");
    if (copyButton) { await copyText(copyButton.dataset.copyValue, "project-message", "Project ID copied."); return; }
    const selectButton = event.target.closest("[data-select-project]");
    const archiveButton = event.target.closest("[data-archive-project], [data-unarchive-project]");
    const deleteButton = event.target.closest("[data-delete-project]");
    try {
      if (selectButton) await api("/api/projects/current", { method: "POST", body: JSON.stringify({ project_id: selectButton.dataset.selectProject }) });
      else if (archiveButton) { const id = archiveButton.dataset.archiveProject || archiveButton.dataset.unarchiveProject; await api(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify({ archived: Boolean(archiveButton.dataset.archiveProject) }) }); }
      else if (deleteButton) { if (!window.confirm("Permanently delete this project and its telemetry?")) return; await api(`/api/projects/${deleteButton.dataset.deleteProject}`, { method: "DELETE" }); }
      else return;
      await loadProjects();
    } catch (error) { showMessage("project-message", error.message, "error"); }
  });
}

async function loadApiKeys() {
  const select = document.getElementById("project-select");
  const table = document.getElementById("api-key-table");
  if (!select || !table || !select.value) {
    return;
  }
  const response = await api(`/api/projects/${select.value}/api-keys`);
  table.innerHTML = response.api_keys.length
    ? response.api_keys.map((key) => `
        <tr>
          <td>${escapeHtml(key.key_prefix)}...</td>
          <td>${key.is_active ? "Active" : "Revoked"}</td>
          <td>${escapeHtml(key.created_at)}</td>
          <td>${escapeHtml(key.last_used_at || "--")}</td>
          <td>
            ${key.is_active
              ? `<button class="danger" data-delete-key="${escapeHtml(key.id)}">Revoke</button>`
              : `<span class="muted">Revoked</span>`}
          </td>
        </tr>
      `).join("")
    : `<tr><td colspan="5" class="muted">No API keys yet.</td></tr>`;
}

function initApiKeys() {
  const select = document.getElementById("project-select");
  const createButton = document.getElementById("create-key-button");
  const regenerateButton = document.getElementById("regenerate-key-button");
  if (!select || !createButton) {
    return;
  }
  select.addEventListener("change", async () => {
    updateManualProjectId();
    await loadApiKeys();
  });
  async function requestNewApiKey(path, successMessage) {
    if (!select.value) {
      showMessage("api-key-message", "Create a project first.", "error");
      return;
    }
    try {
      const response = await api(path, {
        method: "POST",
        body: "{}",
      });
      const keyInput = document.getElementById("new-api-key");
      keyInput.value = response.api_key;
      keyInput.type = "text";
      keyInput.focus();
      keyInput.select();
      const copyKeyButton = document.getElementById("copy-api-key-button");
      const showKeyButton = document.getElementById("show-api-key-button");
      if (copyKeyButton) {
        copyKeyButton.disabled = false;
      }
      if (showKeyButton) {
        showKeyButton.disabled = false;
        showKeyButton.textContent = "Hide API Key";
      }
      showMessage("api-key-message", successMessage, "success");
      await loadApiKeys();
    } catch (error) {
      if (error.status === 404) {
        window.history.replaceState({}, "", "/api-keys");
        await loadProjects();
        showMessage(
          "api-key-message",
          "That project no longer exists. Create or select a project, then generate the API key again.",
          "error",
        );
        return;
      }
      showMessage("api-key-message", error.message, "error");
    }
  }
  createButton.addEventListener("click", async () => {
    await requestNewApiKey(
      `/api/projects/${select.value}/api-keys`,
      "API key generated. Copy it now; Matrixs will not show it again.",
    );
  });
  regenerateButton?.addEventListener("click", async () => {
    const confirmed = window.confirm("Regenerate this project's API key? All active keys for this project will be revoked.");
    if (!confirmed) {
      return;
    }
    await requestNewApiKey(
      `/api/projects/${select.value}/api-keys/regenerate`,
      "API key regenerated. Previous active keys were revoked. Copy the new key now.",
    );
  });
  document.getElementById("show-api-key-button")?.addEventListener("click", (event) => {
    const keyInput = document.getElementById("new-api-key");
    const showing = keyInput.type === "text";
    keyInput.type = showing ? "password" : "text";
    event.currentTarget.textContent = showing ? "Show API Key" : "Hide API Key";
  });
  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-target]");
    if (copyButton) {
      const target = document.getElementById(copyButton.dataset.copyTarget);
      const value = ("value" in (target || {}) ? target.value : target?.textContent)?.trim();
      if (!value) {
        return;
      }
      const messageId = copyButton.dataset.copyMessage || (target.id === "new-api-key" ? "api-key-message" : "connection-message");
      await copyText(value, messageId, "Copied to clipboard.");
      return;
    }
    const button = event.target.closest("[data-delete-key]");
    if (!button) {
      return;
    }
    try {
      await api(`/api/projects/${select.value}/api-keys/${button.dataset.deleteKey}`, {
        method: "DELETE",
      });
      await loadApiKeys();
    } catch (error) {
      showMessage("api-key-message", error.message, "error");
    }
  });
}

function updateManualProjectId() {
  const select = document.getElementById("project-select");
  const output = document.getElementById("manual-project-id");
  const name = document.getElementById("manual-project-name");
  if (output) {
    output.textContent = select?.value || "Create a project first";
  }
  if (name) {
    name.textContent = select?.selectedOptions?.[0]?.textContent || "Create a project first";
  }
}

async function copyText(value, messageId, successMessage) {
  try {
    await navigator.clipboard.writeText(value);
    showMessage(messageId, successMessage, "success");
  } catch (_) {
    showMessage(messageId, "Select and copy the value shown on the page.", "success");
  }
}

function installCommandText(kind) {
  if (kind === "pypi") {
    return "pip install --upgrade git+https://github.com/Tejaswin846/software-reliability-engine.git";
  }
  if (kind === "github") {
    return "pip install --upgrade git+https://github.com/Tejaswin846/software-reliability-engine.git";
  }
  if (kind === "local") {
    return "pip install -e .";
  }
  return "";
}

function updateInstallCommands() {
  const fields = {
    "install-command-pypi": installCommandText("pypi"),
    "install-command-github": installCommandText("github"),
    "install-command-local": installCommandText("local"),
  };
  Object.entries(fields).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = value;
    }
  });
}

async function copyInstallCommand(targetId) {
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  const text = target.textContent.trim();
  try {
    await navigator.clipboard.writeText(text);
    showMessage("install-message", "Copied command.", "success");
  } catch (_) {
    showMessage("install-message", text, "success");
  }
}

function initInstallPage() {
  const root = document.getElementById("install-sdk-page");
  if (!root) {
    return;
  }

  updateInstallCommands();
  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-target]");
    if (copyButton) {
      await copyInstallCommand(copyButton.dataset.copyTarget);
      return;
    }

  });

}

document.addEventListener("DOMContentLoaded", async () => {
  initLogin();
  initRegister();
  initPasswordResetRequest();
  initPasswordUpdate();
  wireLogout();
  initInstallPage();
  if (document.body.dataset.requiresAuth === "true") {
    const user = await requireSession();
    if (!user) {
      return;
    }
    initProjects();
    initApiKeys();
    await loadProjects();
  }
});
