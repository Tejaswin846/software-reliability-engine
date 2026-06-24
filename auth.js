(function () {
  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      throw new Error(body.detail || body.message || `Request failed: ${response.status}`);
    }
    return body;
  }

  async function session() {
    return request("/auth/me");
  }

  async function logout() {
    try {
      await request("/auth/logout", { method: "POST", body: "{}" });
    } finally {
      localStorage.removeItem("software_access_token");
      window.location.href = "/login";
    }
  }

  async function protectPage() {
    if (document.body.dataset.requiresAuth !== "true") {
      return null;
    }
    try {
      const response = await session();
      document.querySelectorAll("[data-user-email], #user-label").forEach((element) => {
        element.textContent = response.user.email;
      });
      document.body.dataset.authReady = "true";
      return response.user;
    } catch (_) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
      return null;
    }
  }

  function wireLogout() {
    document.querySelectorAll("[data-logout], #logout-button").forEach((button) => {
      if (button.dataset.logoutWired === "true") {
        return;
      }
      button.dataset.logoutWired = "true";
      button.addEventListener("click", logout);
    });
  }

  window.SoftwareAuth = {
    request,
    session,
    logout,
    protectPage,
    wireLogout,
  };

  document.addEventListener("DOMContentLoaded", () => {
    wireLogout();
    protectPage();
  });
})();
