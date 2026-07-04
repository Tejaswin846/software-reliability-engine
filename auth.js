(function () {
  const TOKEN_KEY = "software_clerk_session_token";
  const USER_KEY = "software_auth_user";
  let configPromise = null;
  let clerkPromise = null;
  let clerk = null;
  const scriptPromises = {};

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

  function clerkFrontendApi(config) {
    const publishableKey = config.clerk_publishable_key || "";
    const encoded = publishableKey.split("_").slice(2).join("_");
    if (encoded) {
      try {
        const decoded = atob(encoded).replace(/\$$/, "");
        if (decoded) return decoded;
      } catch (_error) {
        // Fall back to the issuer host below.
      }
    }
    try {
      return new URL(config.clerk_jwt_issuer).host;
    } catch (_error) {
      return "";
    }
  }

  function loadScriptOnce(id, src, attributes = {}) {
    if (document.getElementById(id)) return scriptPromises[id] || Promise.resolve();
    if (!scriptPromises[id]) {
      scriptPromises[id] = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.id = id;
        script.src = src;
        script.async = true;
        script.crossOrigin = "anonymous";
        Object.entries(attributes).forEach(([key, value]) => {
          if (value !== undefined && value !== null) script.setAttribute(key, String(value));
        });
        script.onload = resolve;
        script.onerror = () => reject(new Error("Could not load Clerk authentication."));
        document.head.appendChild(script);
      });
    }
    return scriptPromises[id];
  }

  async function loadClerkSdk(config) {
    if (window.Clerk) return;
    const frontendApi = clerkFrontendApi(config);
    if (!frontendApi) {
      throw new Error("Clerk frontend API could not be resolved from the publishable key.");
    }
    const baseUrl = `https://${frontendApi}/npm`;
    await loadScriptOnce("software-clerk-ui", `${baseUrl}/@clerk/ui@latest/dist/ui.browser.js`);
    await loadScriptOnce(
      "software-clerk-js",
      `${baseUrl}/@clerk/clerk-js@latest/dist/clerk.browser.js`,
      { "data-clerk-publishable-key": config.clerk_publishable_key }
    );
  }

  async function createClerkInstance(config) {
    const exported = window.Clerk;
    if (!exported) {
      throw new Error("Clerk loaded, but no Clerk object was found.");
    }
    if (typeof exported === "function") {
      return new exported(config.clerk_publishable_key);
    }
    if (exported.Clerk && typeof exported.Clerk === "function") {
      return new exported.Clerk(config.clerk_publishable_key);
    }
    if (exported.default && typeof exported.default === "function") {
      return new exported.default(config.clerk_publishable_key);
    }
    if (exported.default && typeof exported.default.load === "function") {
      return exported.default;
    }
    if (typeof exported.load === "function") {
      return exported;
    }
    throw new Error("Clerk loaded, but this browser bundle is unsupported.");
  }

  async function loadLegacyClerkSdk(config) {
    try {
      await loadScriptOnce(
        "software-clerk-js-legacy",
        "https://cdn.jsdelivr.net/npm/@clerk/clerk-js@latest/dist/clerk.browser.js",
        { "data-clerk-publishable-key": config.clerk_publishable_key }
      );
      return true;
    } catch (_error) {
      await loadScriptOnce(
        "software-clerk-js-unpkg",
        "https://unpkg.com/@clerk/clerk-js@latest/dist/clerk.browser.js",
        { "data-clerk-publishable-key": config.clerk_publishable_key }
      );
      return true;
    }
  }

  async function ensureClerk() {
    if (!clerkPromise) {
      clerkPromise = (async () => {
        const config = await loadConfig();
        if (!config.configured || !config.clerk_publishable_key) {
          throw new Error("Clerk is not configured for this Software deployment.");
        }
        try {
          await loadClerkSdk(config);
        } catch (_error) {
          await loadLegacyClerkSdk(config);
        }
        clerk = await createClerkInstance(config);
        await clerk.load({ publishableKey: config.clerk_publishable_key });
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

  function requestedRedirect(defaultPath) {
    const queryNext = new URLSearchParams(window.location.search).get("next");
    if (queryNext && queryNext.startsWith("/")) return queryNext;
    return defaultPath || "/projects";
  }

  function redirectOptions(path) {
    return {
      redirectUrl: path,
      afterSignInUrl: path,
      afterSignUpUrl: path,
      fallbackRedirectUrl: path,
      signInFallbackRedirectUrl: path,
      signUpFallbackRedirectUrl: path,
    };
  }

  async function withBusy(element, action) {
    if (element?.dataset?.authBusy === "true") return null;
    const previousText = element?.textContent;
    if (element) {
      element.dataset.authBusy = "true";
      element.setAttribute("aria-busy", "true");
      if ("disabled" in element) element.disabled = true;
      if (element.dataset.loadingText) element.textContent = element.dataset.loadingText;
    }
    try {
      return await action();
    } finally {
      if (element) {
        delete element.dataset.authBusy;
        element.removeAttribute("aria-busy");
        if ("disabled" in element) element.disabled = false;
        if (element.dataset.loadingText && previousText) element.textContent = previousText;
      }
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

  async function openSignIn(redirectPath) {
    try {
      await ensureClerk();
      clerk.openSignIn(redirectOptions(redirectPath || requestedRedirect("/dashboard")));
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  async function openSignUp(redirectPath) {
    try {
      await ensureClerk();
      clerk.openSignUp(redirectOptions(redirectPath || "/projects"));
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  async function openPasswordReset(redirectPath) {
    try {
      await ensureClerk();
      clerk.openSignIn({
        ...redirectOptions(redirectPath || "/dashboard"),
        initialValues: {
          emailAddress: qs("[data-auth-email]")?.value || qs("input[type='email']")?.value || "",
        },
      });
      showAuthMessage("Choose forgot password in the Clerk sign-in flow.", "success");
    } catch (error) {
      showAuthMessage(error.message, "error");
    }
  }

  async function openUserProfile() {
    try {
      await ensureClerk();
      if (!clerk.user) {
        await openSignIn("/dashboard");
        return;
      }
      clerk.openUserProfile();
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
    document.querySelectorAll("[data-user-name]").forEach((element) => {
      if (user?.name) element.textContent = user.name;
    });
    document.querySelectorAll("[data-logout], [data-clerk-sign-out], #logout-button, [data-auth-signed-in]").forEach((button) => {
      button.style.display = user?.email ? "" : "none";
    });
    document.querySelectorAll("[data-clerk-sign-in], [data-clerk-sign-up], [data-auth-signed-out]").forEach((button) => {
      button.style.display = user?.email ? "none" : "";
    });
    document.documentElement.dataset.authState = user?.email ? "signed-in" : "signed-out";
  }

  function actionRedirect(element, fallback) {
    const value = element?.dataset?.authRedirect || element?.getAttribute?.("href") || fallback;
    return value && value.startsWith("/") ? value : fallback;
  }

  function wireClerkActions() {
    document.addEventListener("click", (event) => {
      const target = event.target.closest(
        "[data-clerk-sign-in], [data-clerk-sign-up], [data-clerk-reset], [data-clerk-user-profile], [data-clerk-manage-account], [data-clerk-sign-out]"
      );
      if (!target) return;
      event.preventDefault();
      if (target.matches("[data-clerk-sign-in]")) {
        withBusy(target, () => openSignIn(actionRedirect(target, "/dashboard")));
      } else if (target.matches("[data-clerk-sign-up]")) {
        withBusy(target, () => openSignUp(actionRedirect(target, "/projects")));
      } else if (target.matches("[data-clerk-reset]")) {
        withBusy(target, () => openPasswordReset(actionRedirect(target, "/dashboard")));
      } else if (target.matches("[data-clerk-user-profile], [data-clerk-manage-account]")) {
        withBusy(target, () => openUserProfile());
      } else if (target.matches("[data-clerk-sign-out]")) {
        withBusy(target, () => logout());
      }
    });
  }

  function installDashboardFetchFallback() {
    if (window.__softwareDashboardFetchFallbackInstalled) return;
    window.__softwareDashboardFetchFallbackInstalled = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
      const rawUrl = typeof input === "string" ? input : input?.url;
      let pathname = "";
      try {
        pathname = new URL(rawUrl || "", window.location.href).pathname;
      } catch (_error) {
        pathname = "";
      }
      if (pathname !== "/api/me/dashboard") {
        return originalFetch(input, init);
      }

      const nextInit = Object.assign({}, init || {});
      const headers = new Headers(nextInit.headers || input?.headers || {});
      headers.set("Accept", headers.get("Accept") || "application/json");
      const token = await authToken();
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      nextInit.credentials = nextInit.credentials || "same-origin";
      nextInit.headers = headers;

      const response = await originalFetch(input, nextInit);
      if ([401, 403, 404].includes(response.status)) {
        return originalFetch("/api/dashboard", {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
      }
      return response;
    };
  }

  installDashboardFetchFallback();

  window.SoftwareAuth = {
    request,
    session,
    logout,
    protectPage,
    wireLogout,
    openSignIn,
    openSignUp,
    openPasswordReset,
    openUserProfile,
    ready: ensureClerk,
  };

  document.addEventListener("DOMContentLoaded", () => {
    wireLogout();
    wireClerkActions();
    ensureClerk().catch((error) => showAuthMessage(error.message, "error"));
    protectPage();
  });
})();
