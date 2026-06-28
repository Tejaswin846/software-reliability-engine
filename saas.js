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
                <a class="button secondary" href="/api-keys?project=${encodeURIComponent(project.id)}">API Keys</a>
                <button class="danger" data-delete-project="${escapeHtml(project.id)}">Delete</button>
              </div>
            </div>
          </article>
        `).join("")
      : `<div class="card muted">No projects yet. Create one to connect an agent.</div>`;
  }
  if (select) {
    select.innerHTML = response.projects.map((project) => (
      `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`
    )).join("");
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
  if (!select || !createButton) {
    return;
  }
  select.addEventListener("change", loadApiKeys);
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
      showMessage("api-key-message", "API key created. Copy it now.", "success");
      await loadApiKeys();
    } catch (error) {
      showMessage("api-key-message", error.message, "error");
    }
  });
  document.addEventListener("click", async (event) => {
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
    return "pip install software-sdk";
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
  const apiUrlInput = document.getElementById("install-api-url");
  const apiKeyInput = document.getElementById("install-api-key");
  const projectNameInput = document.getElementById("install-project-name");
  const apiUrl = (apiUrlInput?.value || window.location.origin).replace(/\/+$/, "");
  const apiKey = apiKeyInput?.value || "sw_your_key";
  const project = selectedInstallProject();
  const projectName = projectNameInput?.value || project?.name || "my-agent";
  const setup = [
    "pip install git+https://github.com/Tejaswin846/software-reliability-engine.git",
    `software login --api-url ${apiUrl} --api-key ${apiKey} --project-name ${projectName}`,
    "software init",
    "software test",
    "software status",
  ].join("\n");

  const fields = {
    "install-command-pypi": installCommandText("pypi"),
    "install-command-github": installCommandText("github"),
    "install-command-local": installCommandText("local"),
    "install-command-setup": setup,
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
  let response;
  try {
    response = await api("/api/projects");
  } catch (error) {
    if (error.status === 401) {
      select.innerHTML = `<option value="">Sign in to select a project</option>`;
      const projectNameLabel = document.getElementById("install-project-name-label");
      if (projectNameLabel) {
        projectNameLabel.textContent = "Sign in for cloud setup";
      }
      updateInstallCommands();
      showMessage("install-message", "SDK install commands are public. Sign in only to generate API keys or test cloud ingestion.", "success");
      return;
    }
    throw error;
  }
  select.innerHTML = response.projects.length
    ? response.projects.map((project) => (
      `<option value="${escapeHtml(project.id)}" data-project-name="${escapeHtml(project.name)}">${escapeHtml(project.name)}</option>`
    )).join("")
    : `<option value="">Create a project first</option>`;

  const selected = selectedInstallProject();
  const projectNameInput = document.getElementById("install-project-name");
  const projectNameLabel = document.getElementById("install-project-name-label");
  if (projectNameInput && selected) {
    projectNameInput.value = selected.name;
  }
  if (projectNameLabel) {
    projectNameLabel.textContent = selected ? selected.name : "No project selected";
  }
  updateInstallCommands();
}

function initInstallPage() {
  const root = document.getElementById("install-sdk-page");
  if (!root) {
    return;
  }

  const apiUrlInput = document.getElementById("install-api-url");
  const apiKeyInput = document.getElementById("install-api-key");
  const projectNameInput = document.getElementById("install-project-name");
  const projectSelect = document.getElementById("install-project-select");
  if (apiUrlInput) {
    apiUrlInput.value = window.location.origin;
  }
  const savedKey = sessionStorage.getItem("software_install_api_key");
  if (apiKeyInput && savedKey) {
    apiKeyInput.value = savedKey;
  }

  [apiUrlInput, apiKeyInput, projectNameInput].forEach((input) => {
    if (input) {
      input.addEventListener("input", updateInstallCommands);
    }
  });
  if (projectSelect) {
    projectSelect.addEventListener("change", () => {
      const selected = selectedInstallProject();
      const label = document.getElementById("install-project-name-label");
      if (projectNameInput && selected) {
        projectNameInput.value = selected.name;
      }
      if (label) {
        label.textContent = selected ? selected.name : "No project selected";
      }
      updateInstallCommands();
    });
  }

  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest("[data-copy-target]");
    if (copyButton) {
      await copyInstallCommand(copyButton.dataset.copyTarget);
      return;
    }

    const generateButton = event.target.closest("#generate-install-api-key");
    if (generateButton) {
      const project = selectedInstallProject();
      if (!project) {
        showMessage("install-message", "Create a project before generating an API key.", "error");
        return;
      }
      try {
        generateButton.disabled = true;
        const response = await api(`/api/projects/${project.id}/api-keys`, {
          method: "POST",
          body: "{}",
        });
        apiKeyInput.value = response.api_key;
        sessionStorage.setItem("software_install_api_key", response.api_key);
        updateInstallCommands();
        showMessage("install-message", "API key generated. Copy or use it now; it is only shown once.", "success");
      } catch (error) {
        showMessage("install-message", error.message, "error");
      } finally {
        generateButton.disabled = false;
      }
      return;
    }

    const testButton = event.target.closest("#test-install-connection");
    if (testButton) {
      const apiUrl = (apiUrlInput?.value || window.location.origin).replace(/\/+$/, "");
      const apiKey = apiKeyInput?.value.trim();
      const projectName = projectNameInput?.value.trim() || selectedInstallProject()?.name || "my-agent";
      if (!apiKey) {
        showMessage("install-message", "Enter or generate an API key before testing.", "error");
        return;
      }
      try {
        testButton.disabled = true;
        const response = await fetch(`${apiUrl}/api/sdk/test-workflow`, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Software-API-Key": apiKey,
          },
          body: JSON.stringify({
            project_name: projectName,
            workflow_name: "install-page-test",
            metadata: { source: "install_page_button" },
          }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok || body.ok === false) {
          throw new Error(body.detail || body.message || `SDK test returned ${response.status}`);
        }
        const status = document.getElementById("install-status");
        if (status) {
          status.textContent = `Connected. Test workflow ${body.workflow_id} recorded.`;
        }
        showMessage("install-message", "Connection test passed. Open the dashboard to view the workflow.", "success");
      } catch (error) {
        const status = document.getElementById("install-status");
        if (status) {
          status.textContent = "Connection test failed.";
        }
        showMessage("install-message", error.message, "error");
      } finally {
        testButton.disabled = false;
      }
    }
  });

  loadInstallProjects().catch((error) => {
    showMessage("install-message", error.message, "error");
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
