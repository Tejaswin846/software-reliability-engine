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

async function loadProjects() {
  const list = document.getElementById("project-list");
  const select = document.getElementById("project-select");
  if (!list && !select) {
    return;
  }
  const response = await api("/api/projects");
  if (list) {
    list.innerHTML = response.projects.length
      ? response.projects.map((project) => `
          <article class="card">
            <div class="row">
              <div>
                <h2>${escapeHtml(project.name)}</h2>
                <p class="muted">${escapeHtml(project.id)}</p>
                <p class="muted">${project.workflow_count || 0} workflows - ${project.api_key_count || 0} active keys</p>
              </div>
              <div class="nav">
                <a class="button secondary" href="/api-keys?project=${encodeURIComponent(project.id)}">Connect</a>
                <button class="danger" data-delete-project="${escapeHtml(project.id)}">Delete</button>
              </div>
            </div>
          </article>
        `).join("")
      : `<div class="card muted">No projects yet. Create one to connect an agent.</div>`;
  }
  if (select) {
    const hasProjects = response.projects.length > 0;
    select.innerHTML = hasProjects
      ? response.projects.map((project) => (
        `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`
      )).join("")
      : `<option value="">Create a project first</option>`;
    const connectionButton = document.getElementById("create-connection-command");
    const keyButton = document.getElementById("create-key-button");
    const emptyProjectHelp = document.getElementById("empty-project-help");
    if (connectionButton) {
      connectionButton.disabled = !hasProjects;
    }
    if (keyButton) {
      keyButton.disabled = !hasProjects;
    }
    if (emptyProjectHelp) {
      emptyProjectHelp.hidden = hasProjects;
    }
    const query = new URLSearchParams(window.location.search);
    const selected = query.get("project");
    if (selected) {
      select.value = selected;
    }
    await loadApiKeys();
  }
}

function initProjects() {
  const form = document.getElementById("project-form");
  if (!form) {
    return;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name: form.name.value }),
      });
      form.reset();
      showMessage("project-message", "Project created.", "success");
      await loadProjects();
    } catch (error) {
      showMessage("project-message", error.message, "error");
    }
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete-project]");
    if (!button) {
      return;
    }
    try {
      await api(`/api/projects/${button.dataset.deleteProject}`, { method: "DELETE" });
      await loadProjects();
    } catch (error) {
      showMessage("project-message", error.message, "error");
    }
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
            <button class="danger" data-delete-key="${escapeHtml(key.id)}">Revoke</button>
          </td>
        </tr>
      `).join("")
    : `<tr><td colspan="5" class="muted">No API keys yet.</td></tr>`;
}

function initApiKeys() {
  const select = document.getElementById("project-select");
  const createButton = document.getElementById("create-key-button");
  const connectionButton = document.getElementById("create-connection-command");
  if (!select || !createButton || !connectionButton) {
    return;
  }
  select.addEventListener("change", async () => {
    const result = document.getElementById("connection-result");
    if (result) {
      result.hidden = true;
    }
    await loadApiKeys();
  });
  connectionButton.addEventListener("click", async () => {
    if (!select.value) {
      showMessage("connection-message", "Create a project first.", "error");
      return;
    }
    try {
      connectionButton.disabled = true;
      connectionButton.textContent = "Creating secure command...";
      const response = await api(`/api/projects/${select.value}/connection-token`, {
        method: "POST",
        body: "{}",
      });
      document.getElementById("connection-command").textContent = response.connection.command;
      document.getElementById("connection-expiry").textContent =
        `Expires ${new Date(response.connection.expires_at).toLocaleString()} and works once.`;
      document.getElementById("connection-result").hidden = false;
      showMessage("connection-message", "One-time Matrixs connection command created.", "success");
    } catch (error) {
      showMessage("connection-message", error.message, "error");
    } finally {
      connectionButton.disabled = false;
      connectionButton.textContent = "Generate connection command";
    }
  });
  createButton.addEventListener("click", async () => {
    if (!select.value) {
      showMessage("api-key-message", "Create a project first.", "error");
      return;
    }
    try {
      const response = await api(`/api/projects/${select.value}/api-keys`, {
        method: "POST",
        body: "{}",
      });
      document.getElementById("new-api-key").textContent = response.api_key;
      showMessage("api-key-message", "Permanent API key created. Copy it now, then keep it secret.", "success");
      await loadApiKeys();
    } catch (error) {
      showMessage("api-key-message", error.message, "error");
    }
  });
  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest('[data-copy-target="connection-command"]');
    if (copyButton) {
      const command = document.getElementById("connection-command")?.textContent.trim();
      if (!command) {
        return;
      }
      try {
        await navigator.clipboard.writeText(command);
        showMessage("connection-message", "Connection command copied.", "success");
      } catch (_) {
        showMessage("connection-message", "Select and copy the command shown below.", "success");
      }
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

function installCommandText(kind) {
  if (kind === "pypi") {
    return "pip install git+https://github.com/Tejaswin846/software-reliability-engine.git";
  }
  if (kind === "github") {
    return "pip install git+https://github.com/Tejaswin846/software-reliability-engine.git";
  }
  if (kind === "local") {
    return "pip install -e .";
  }
  return "";
}

function selectedInstallProject() {
  const select = document.getElementById("install-project-select");
  if (!select || !select.value) {
    return null;
  }
  const option = select.options[select.selectedIndex];
  return {
    id: select.value,
    name: option?.dataset.projectName || option?.textContent || "my-agent",
  };
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

async function loadInstallProjects() {
  const select = document.getElementById("install-project-select");
  if (!select) {
    return;
  }
  const response = await api("/api/projects");
  select.innerHTML = response.projects.length
    ? response.projects.map((project) => (
      `<option value="${escapeHtml(project.id)}" data-project-name="${escapeHtml(project.name)}">${escapeHtml(project.name)}</option>`
    )).join("")
    : `<option value="">Create a project first</option>`;

  const result = document.getElementById("install-connection-result");
  if (result) {
    result.hidden = true;
  }
  updateInstallCommands();
}

function initInstallPage() {
  const root = document.getElementById("install-sdk-page");
  if (!root) {
    return;
  }

  const projectSelect = document.getElementById("install-project-select");
  if (projectSelect) {
    projectSelect.addEventListener("change", () => {
      const result = document.getElementById("install-connection-result");
      if (result) {
        result.hidden = true;
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-target]");
    if (copyButton) {
      await copyInstallCommand(copyButton.dataset.copyTarget);
      return;
    }

    const generateButton = event.target.closest("#generate-install-connection");
    if (generateButton) {
      const project = selectedInstallProject();
      if (!project) {
        showMessage("install-message", "Create a project before generating a connection command.", "error");
        return;
      }
      try {
        generateButton.disabled = true;
        generateButton.textContent = "Creating secure command...";
        const response = await api(`/api/projects/${project.id}/connection-token`, {
          method: "POST",
          body: "{}",
        });
        const setup = [
          installCommandText("github"),
          response.connection.command,
          "matrixs status",
          "matrixs run",
        ].join("\n");
        document.getElementById("install-command-setup").textContent = setup;
        document.getElementById("install-connection-expiry").textContent =
          `Expires ${new Date(response.connection.expires_at).toLocaleString()} and works once.`;
        document.getElementById("install-connection-result").hidden = false;
        showMessage("install-message", "One-time Matrixs connection command created.", "success");
      } catch (error) {
        showMessage("install-message", error.message, "error");
      } finally {
        generateButton.disabled = false;
        generateButton.textContent = "Generate connection command";
      }
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
