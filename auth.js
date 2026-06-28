(function () {
  const TOKEN_KEY = "software_clerk_session_token";
  const USER_KEY = "software_auth_user";
  let configPromise = null;
  let clerkPromise = null;
  let clerk = null;

  function qs(selector) {
    return document.querySelector(selector);
  }

  function showAuthMessage(text, kind) {
    const element = qs("[data-auth-message], #login-message, #register-message, #forgot-password-message, #reset-password-message");
    if (!element) return;
    element.textContent = text || "";
    element.className = `message visible ${kind || "success"}`;
  }

  async function loadConfig() {
    if (!configPromise) {
      configPromise = fetch("/auth/config", { headers: { Accept: "application/json" } })
        .then(async (response) => {
          const body = await response.json().catch(() => ({}));
          if (!response.ok || body.ok === false) {
            throw new Error(body.detail || body.message || "Authentication configuration is unavailable.");
          }
          return body;
        });
    }
    return configPromise;
  }

  function loadClerkSdk() {
    return new Promise((resolve, reject) => {
      if (window.Clerk) return resolve();
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/@clerk/clerk-js@latest/dist/clerk.browser.js";
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Could not load Clerk authentication."));
      document.head.appendChild(script);
    });
  }

  async function ensureClerk() {
    if (!clerkPromise) {
      clerkPromise = (async () => {
        const config = await loadConfig();
        if (!config.configured || !config.clerk_publishable_key) {
          throw new Error("Clerk is not configured for this Software deployment.");
        }
        await loadClerkSdk();
        clerk = new window.Clerk(config.clerk_publishable_key);
        await clerk.load();
        await refreshSession();
        clerk.addListener?.(async ({ user, session }) => {
          if (user || session) {
            await refreshSession();
          } else {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
          }
          updateAuthUi();
        });
        updateAuthUi();
        return clerk;
      })();
    }
    return clerkPromise;
  }

  function userFromClerk(user) {
    if (!user) return null;
    const email = user.primaryEmailAddress?.emailAddress || user.emailAddresses?.[0]?.emailAddress || "";
    return {
      id: user.id,
      email,
      name: user.fullName || user.username || email || "Software user",
      provider: "clerk",
    };
  }

  async function refreshSession() {
    if (!clerk || !clerk.session) return "";
    const token = await clerk.session.getToken();
    if (token) localStorage.setItem(TOKEN_KEY, token);
    const user = userFromClerk(clerk.user);
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    return token || "";
  }

  async function authToken() {
    try {
      await ensureClerk();
      return await refreshSession();
    } catch (_error) {
      return localStorage.getItem(TOKEN_KEY) || "";
    }
  }

  async function request(path, options = {}) {
    const token = await authToken();
    const headers = new Headers(options.headers || {});
    headers.set("Accept", headers.get("Accept") || "application/json");
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers,
    });
    const body = await response.json().catch(() => ({}));
    if (body.connection_required && window.SoftwareApps?.requireConnection) {
      window.SoftwareApps.requireConnection(body);
      return body;
    }
    if (body.confirmation_required && window.SoftwareAI?.requestConfirmation) {
      return window.SoftwareAI.requestConfirmation(body);
    }
    if (!response.ok || body.ok === false) {
      const error = new Error(body.detail || body.error || body.message || `Request failed: ${response.status}`);
      error.response = body;
      error.status = response.status;
      throw error;
    }
    return body;
  }

  async function session() {
    return request("/auth/me");
  }

  async function logout() {
    try {
      await ensureClerk();
      await clerk?.signOut?.();
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      window.location.href = "/login";
    }
  }

  async function protectPage() {
    if (document.body.dataset.requiresAuth !== "true") return null;
    try {
      await ensureClerk();
      if (!clerk.user || !clerk.session) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${next}`;
        return null;
      }
      const response = await session();
      document.querySelectorAll("[data-user-email], #user-label").forEach((element) => {
        element.textContent = response.user.email;
      });
      document.body.dataset.authReady = "true";
      return response.user;
    } catch (_error) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
      return null;
    }
  }

  function wireLogout() {
    document.querySelectorAll("[data-logout], #logout-button").forEach((button) => {
      if (button.dataset.logoutWired === "true") return;
      button.dataset.logoutWired = "true";
      button.addEventListener("click", logout);
    });
  }

  async function openSignIn() {
    try {
      await ensureClerk();
      const requestedNext = new URLSearchParams(window.location.search).get("next");
      const redirectUrl = requestedNext && requestedNext.startsWith("/") ? requestedNext : "/projects";
      clerk.openSignIn({ redirectUrl });
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  async function openSignUp() {
    try {
      await ensureClerk();
      clerk.openSignUp({ redirectUrl: "/projects" });
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  async function openPasswordReset() {
    try {
      await ensureClerk();
      clerk.openSignIn({ redirectUrl: "/projects" });
      showAuthMessage("Choose forgot password in the Clerk sign-in flow.", "success");
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  function updateAuthUi() {
    const cached = localStorage.getItem(USER_KEY);
    let user = null;
    try {
      user = cached ? JSON.parse(cached) : null;
    } catch (_error) {
      user = null;
    }
    document.querySelectorAll("[data-user-email], #user-label").forEach((element) => {
      if (user?.email) element.textContent = user.email;
    });
    document.querySelectorAll("[data-logout], #logout-button").forEach((button) => {
      button.style.display = user?.email ? "" : "none";
    });
    document.querySelectorAll("[data-clerk-sign-in]").forEach((button) => {
      button.style.display = user?.email ? "none" : "";
    });
  }

  window.SoftwareAuth = {
    request,
    session,
    logout,
    protectPage,
    wireLogout,
    openSignIn,
    openSignUp,
    openPasswordReset,
    ready: ensureClerk,
  };

  document.addEventListener("DOMContentLoaded", () => {
    wireLogout();
    document.querySelectorAll("[data-clerk-sign-in]").forEach((button) => button.addEventListener("click", openSignIn));
    document.querySelectorAll("[data-clerk-sign-up]").forEach((button) => button.addEventListener("click", openSignUp));
    document.querySelectorAll("[data-clerk-reset]").forEach((button) => button.addEventListener("click", openPasswordReset));
    ensureClerk().catch((error) => showAuthMessage(error.message, "error"));
    protectPage();
  });
})();
