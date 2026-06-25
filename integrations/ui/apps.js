const appState = {
  apps: [],
  category: "All",
  search: "",
  timer: null,
};

function appApi(path, options = {}) {
  return window.SoftwareAuth.request(path, options);
}

function appEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appMessage(text, kind = "success") {
  const element = document.getElementById("apps-message");
  element.textContent = text;
  element.className = `message visible ${kind}`;
}

function initials(name) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function logoMarkup(app) {
  const source = `https://cdn.simpleicons.org/${encodeURIComponent(app.icon)}`;
  return `
    <div class="app-logo">
      <img src="${source}" alt="" onerror="this.hidden=true;this.nextElementSibling.hidden=false">
      <span hidden>${appEscape(initials(app.name))}</span>
    </div>
  `;
}

function formatSync(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function visibleApps() {
  const query = appState.search.trim().toLowerCase();
  return appState.apps.filter((app) => {
    const categoryMatch = appState.category === "All" || app.category === appState.category;
    const searchMatch =
      !query ||
      app.name.toLowerCase().includes(query) ||
      app.description.toLowerCase().includes(query) ||
      app.category.toLowerCase().includes(query);
    return categoryMatch && searchMatch;
  });
}

function renderCategories() {
  const categories = ["All", "Communication", "Development", "Storage", "Productivity", "AI", "Database"];
  document.getElementById("category-tabs").innerHTML = categories
    .map(
      (category) => `
        <button
          type="button"
          class="category-tab ${category === appState.category ? "active" : ""}"
          data-category="${appEscape(category)}"
        >${appEscape(category)}</button>
      `,
    )
    .join("");
}

function renderApps() {
  const apps = visibleApps();
  document.getElementById("connected-count").textContent = String(
    appState.apps.filter((app) => app.connected).length,
  );
  const grid = document.getElementById("apps-grid");
  if (!apps.length) {
    grid.innerHTML = '<div class="apps-empty">No apps match this search.</div>';
    return;
  }
  grid.innerHTML = apps
    .map((app) => {
      const statusClass = app.connected ? "connected" : "disconnected";
      const statusText = app.connected ? "Connected" : "Not Connected";
      const action = app.connected
        ? `<button type="button" class="disconnect" data-disconnect="${app.id}">Disconnect</button>`
        : `<button type="button" data-connect="${app.id}">Connect</button>`;
      const retry = app.can_retry
        ? `<button type="button" class="retry" data-retry="${app.id}">Retry</button>`
        : "";
      return `
        <article class="app-card ${app.connected ? "connected" : ""}">
          <div class="app-card-header">
            ${logoMarkup(app)}
            <div class="app-title">
              <h2>${appEscape(app.name)}</h2>
              <p>${appEscape(app.description)}</p>
            </div>
            <span class="connection-status ${statusClass}">${statusText}</span>
          </div>
          <div class="app-details">
            <div class="app-detail">
              <span>Connection health</span>
              <strong>${appEscape(app.health)}</strong>
            </div>
            <div class="app-detail">
              <span>Last sync</span>
              <strong>${appEscape(formatSync(app.last_sync_at))}</strong>
            </div>
            <div class="app-detail">
              <span>Permissions</span>
              <button type="button" data-permissions="${app.id}">
                ${app.connected ? `${app.permissions_granted.length} granted` : "View required"}
              </button>
            </div>
          </div>
          <div class="app-actions">${action}${retry}</div>
        </article>
      `;
    })
    .join("");
}

async function loadApps({ quiet = false } = {}) {
  try {
    const response = await appApi("/api/integrations/status");
    appState.apps = response.apps || [];
    renderCategories();
    renderApps();
    if (response.error && !quiet) {
      appMessage("Some connection statuses could not be refreshed. We will try again automatically.", "error");
    }
  } catch (error) {
    if (!quiet) appMessage(error.message, "error");
  }
}

async function connectApp(appId, retry = false) {
  const button = document.querySelector(`[data-${retry ? "retry" : "connect"}="${CSS.escape(appId)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = "Opening...";
  }
  try {
    const response = await appApi("/api/integrations/connect", {
      method: "POST",
      body: JSON.stringify({
        app_id: appId,
        return_to: window.location.pathname + window.location.search,
        retry,
      }),
    });
    window.location.href = response.redirect_url;
  } catch (error) {
    appMessage(error.message, "error");
    await loadApps({ quiet: true });
  }
}

async function disconnectApp(appId) {
  const app = appState.apps.find((item) => item.id === appId);
  try {
    await appApi("/api/integrations/disconnect", {
      method: "POST",
      body: JSON.stringify({ app_id: appId }),
    });
    appMessage(`${app?.name || "App"} disconnected.`);
    await loadApps({ quiet: true });
  } catch (error) {
    appMessage(error.message, "error");
  }
}

function showPermissions(appId) {
  const app = appState.apps.find((item) => item.id === appId);
  if (!app) return;
  const permissions = app.connected && app.permissions_granted.length
    ? app.permissions_granted
    : app.permissions;
  document.getElementById("permissions-title").textContent = "Permissions";
  document.getElementById("permissions-app").textContent =
    `${app.name} · ${app.permission_status}`;
  document.getElementById("permissions-list").innerHTML = permissions
    .map((permission) => `<li>${appEscape(permission)}</li>`)
    .join("");
  document.getElementById("permissions-dialog").hidden = false;
}

function closePermissions() {
  document.getElementById("permissions-dialog").hidden = true;
}

function handleReturnStatus() {
  const query = new URLSearchParams(window.location.search);
  const connected = query.get("integration_connected");
  const error = query.get("integration_error");
  if (connected) {
    const app = appState.apps.find((item) => item.id === connected);
    appMessage(`${app?.name || "App"} connected. Software can use it now.`);
  } else if (error) {
    appMessage("The app connection could not be completed. Please try again.", "error");
  }
}

document.addEventListener("click", (event) => {
  const category = event.target.closest("[data-category]");
  if (category) {
    appState.category = category.dataset.category;
    renderCategories();
    renderApps();
    return;
  }
  const connect = event.target.closest("[data-connect]");
  if (connect) return connectApp(connect.dataset.connect);
  const retry = event.target.closest("[data-retry]");
  if (retry) return connectApp(retry.dataset.retry, true);
  const disconnect = event.target.closest("[data-disconnect]");
  if (disconnect) return disconnectApp(disconnect.dataset.disconnect);
  const permissions = event.target.closest("[data-permissions]");
  if (permissions) return showPermissions(permissions.dataset.permissions);
  if (event.target.closest("[data-close-permissions]")) closePermissions();
});

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("app-search").addEventListener("input", (event) => {
    appState.search = event.target.value;
    renderApps();
  });
  await loadApps();
  handleReturnStatus();
  appState.timer = window.setInterval(() => loadApps({ quiet: true }), 15000);
});
