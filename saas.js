const TOKEN_KEY = "software_access_token";

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) {
    throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
  }
  return body;
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
  if (!getToken()) {
    window.location.href = "/login";
    return null;
  }
  try {
    const response = await api("/auth/me");
    const userLabel = document.getElementById("user-label");
    if (userLabel) {
      userLabel.textContent = response.user.email;
    }
    return response.user;
  } catch (error) {
    clearToken();
    window.location.href = "/login";
    return null;
  }
}

function wireLogout() {
  const button = document.getElementById("logout-button");
  if (!button) {
    return;
  }
  button.addEventListener("click", async () => {
    try {
      await api("/auth/logout", { method: "POST", body: "{}" });
    } catch (_) {
      // Stateless JWT logout is client-side; ignore network failures here.
    }
    clearToken();
    window.location.href = "/login";
  });
}

function initLogin() {
  const form = document.getElementById("login-form");
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
      const response = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setToken(response.access_token);
      window.location.href = "/projects";
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
      setToken(response.access_token);
      window.location.href = "/projects";
    } catch (error) {
      showMessage("register-message", error.message, "error");
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

document.addEventListener("DOMContentLoaded", async () => {
  initLogin();
  initRegister();
  wireLogout();
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
