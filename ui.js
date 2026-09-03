(function matrixsSharedUi() {
  "use strict";

  window.__consoleErrors = window.__consoleErrors || [];
  window.addEventListener("error", function (event) {
    window.__consoleErrors.push(String(event.message || event.error || "Unknown browser error"));
  });
  window.addEventListener("unhandledrejection", function (event) {
    window.__consoleErrors.push(String(event.reason || "Unhandled promise rejection"));
  });

  function icon() {
    return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.25 4.75 7.3v9.4L12 20.75l7.25-4.05V7.3L12 3.25Z" stroke="currentColor" stroke-width="1.8"/><path d="m8.5 12 2.15 2.15 4.85-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  function menuIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  }

  function currentRoute(pathname) {
    if (pathname === "/" || pathname === "/app" || pathname === "/nexora") return "/";
    if (pathname.startsWith("/dashboard")) return "/dashboard";
    if (pathname.startsWith("/projects")) return "/projects";
    if (pathname.startsWith("/billing")) return "/billing";
    if (pathname.startsWith("/onboarding")) return "/onboarding";
    if (pathname.startsWith("/observability")) return "/observability";
    if (pathname.startsWith("/guide") || pathname.startsWith("/code") || pathname.startsWith("/mcp")) return "/guide";
    return "";
  }

  function buildBar() {
    if (!document.body || document.querySelector(".mx-global-bar")) return;

    var pageKind = document.body.dataset.matrixsPage || "";
    var reliabilityApp = pageKind === "reliability" || pageKind === "ai-tester";
    var route = reliabilityApp ? window.location.pathname : currentRoute(window.location.pathname);
    var links = reliabilityApp ? [
      ["/", "Home"],
      ["/dashboard", "Reliability"],
      ["/projects", "Projects"],
      ["/failure-analysis", "Failures"],
      ["/onboarding", "Setup"],
      ["/billing", "Billing"],
      ["/developer-docs", "Docs"]
    ] : [
      ["/", "Workbench"],
      ["/dashboard", "Reliability"],
      ["/onboarding", "Setup"],
      ["/observability", "Observe"],
      ["/guide", "Docs"]
    ];
    var ctaHref = reliabilityApp ? "/onboarding" : "/onboarding";
    var ctaLabel = reliabilityApp ? "Connect a project" : "Protect an app";
    var header = document.createElement("header");
    header.className = "mx-global-bar";
    header.setAttribute("data-ui", "matrixs-global-navigation");
    header.innerHTML =
      '<div class="mx-global-inner">' +
        '<a class="mx-global-brand" href="/" aria-label="Matrixs home">' +
          '<span class="mx-global-mark">' + icon() + '</span>' +
          '<span class="mx-global-wordmark">Matrixs<small>AI reliability platform</small></span>' +
        '</a>' +
        '<nav class="mx-global-nav" id="mx-global-nav" aria-label="Product navigation">' +
          links.map(function (item) {
            var current = item[0] === route ? ' aria-current="page"' : "";
            return '<a href="' + item[0] + '"' + current + '>' + item[1] + '</a>';
          }).join("") +
        '</nav>' +
        '<div class="mx-global-actions">' +
          '<a class="mx-global-cta" href="' + ctaHref + '">' + ctaLabel + '</a>' +
          '<button class="mx-menu-button" type="button" aria-expanded="false" aria-controls="mx-global-nav" aria-label="Open navigation">' + menuIcon() + '</button>' +
        '</div>' +
      '</div>';

    document.body.insertBefore(header, document.body.firstChild);

    var actions = header.querySelector(".mx-global-actions");
    var existingLogout = document.getElementById("logoutBtn");
    if (existingLogout && actions) actions.appendChild(existingLogout);

    var button = header.querySelector(".mx-menu-button");
    var nav = header.querySelector(".mx-global-nav");
    function closeMenu() {
      nav.classList.remove("open");
      button.setAttribute("aria-expanded", "false");
      button.setAttribute("aria-label", "Open navigation");
    }
    button.addEventListener("click", function () {
      var open = !nav.classList.contains("open");
      nav.classList.toggle("open", open);
      button.setAttribute("aria-expanded", String(open));
      button.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    });
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) closeMenu();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu();
    });
    document.addEventListener("click", function (event) {
      if (!header.contains(event.target)) closeMenu();
    });

    document.querySelectorAll(".login-close, .account-close, .voice-close, .wake-close").forEach(function (control) {
      if (!control.hasAttribute("role")) control.setAttribute("role", "button");
      if (!control.hasAttribute("tabindex")) control.setAttribute("tabindex", "0");
      if (!control.hasAttribute("aria-label")) control.setAttribute("aria-label", "Close dialog");
      control.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          control.click();
        }
      });
    });

    if (window.HSStaticMethods && typeof window.HSStaticMethods.autoInit === "function") {
      window.HSStaticMethods.autoInit();
    }
    window.__matrixsUiReady = true;
    document.documentElement.dataset.matrixsUi = "ready";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildBar, { once: true });
  } else {
    buildBar();
  }
})();
