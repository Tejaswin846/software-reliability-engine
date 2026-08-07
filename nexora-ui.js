(function () {
  "use strict";

  const pathname = window.location.pathname;
  const body = document.body;

  function pageGroup() {
    if (pathname === "/" || ["/pricing", "/demo", "/onboarding"].includes(pathname)) return "marketing";
    if (pathname === "/developer-docs" || pathname.startsWith("/docs/")) return "docs";
    if (["/login", "/register", "/forgot-password", "/reset-password"].includes(pathname)) return "auth";
    if (pathname === "/install" || pathname === "/sdk") return "install";
    if (pathname === "/dashboard") return "dashboard";
    return "workspace";
  }

  function pageLabel() {
    const labels = {
      "/pricing": "Plans",
      "/demo": "Product demo",
      "/onboarding": "Onboarding",
      "/install": "Developer SDK",
      "/sdk": "Developer SDK",
      "/login": "Reliability cloud",
      "/register": "Reliability cloud",
      "/forgot-password": "Account recovery",
      "/reset-password": "Account recovery",
      "/projects": "Projects",
      "/api-keys": "API keys",
      "/benchmarks": "Benchmarks",
      "/failures": "Failure analysis",
      "/failure-analysis": "Failure analysis",
      "/apps": "Connected apps",
      "/developer-docs": "Documentation",
    };
    if (pathname.startsWith("/docs/")) return "Documentation";
    return labels[pathname] || "Reliability cloud";
  }

  function icon(path) {
    return `<svg aria-hidden="true" viewBox="0 0 24 24"><path d="${path}"/></svg>`;
  }

  function bindCollapseFallback(button, target) {
    button.addEventListener("click", () => {
      const wasExpanded = button.getAttribute("aria-expanded") === "true";
      window.setTimeout(() => {
        const prelineExpanded = button.getAttribute("aria-expanded") === "true";
        const shouldOpen = prelineExpanded === wasExpanded ? !wasExpanded : prelineExpanded;
        button.setAttribute("aria-expanded", String(shouldOpen));
        target.classList.toggle("open", shouldOpen);
        target.classList.toggle("hidden", !shouldOpen);
      }, 0);
    });
  }

  function normalizeBrandCopy() {
    document.title = document.title.replace(/\bSoftware\b/g, "Nexora");
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const excluded = new Set(["CODE", "PRE", "SCRIPT", "STYLE", "TEXTAREA"]);
    const nodes = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (parent && !excluded.has(parent.tagName) && /\bSoftware\b/.test(node.nodeValue || "")) {
        nodes.push(node);
      }
    }
    nodes.forEach((node) => {
      node.nodeValue = node.nodeValue
        .replace(/\bSoftware\b/g, "Nexora")
        .replace(/\bNexora Nexora\b/g, "Nexora");
    });
  }

  function enhanceBrand(header) {
    const brand = header.querySelector(".brand");
    if (!brand || brand.dataset.nexoraEnhanced) return;
    brand.dataset.nexoraEnhanced = "true";
    brand.setAttribute("aria-label", "Nexora home");
    brand.innerHTML = `
      <span class="nexora-brand-mark" aria-hidden="true">N</span>
      <span class="nexora-brand-copy">
        <strong>Nexora<span aria-hidden="true">+</span></strong>
        <small>${pageLabel()}</small>
      </span>
    `;
  }

  function enhanceTopbar(header, index) {
    enhanceBrand(header);
    const nav = header.querySelector(".nav, .topbar-actions");
    if (!nav || nav.dataset.nexoraEnhanced) return;

    nav.dataset.nexoraEnhanced = "true";
    nav.classList.add("nexora-page-nav", "hs-collapse", "hidden");
    nav.id = nav.id || `nexora-page-navigation-${index}`;
    nav.setAttribute("aria-label", "Page navigation");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "nexora-nav-toggle";
    button.setAttribute("aria-label", "Open navigation");
    button.setAttribute("aria-controls", nav.id);
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("data-hs-collapse", `#${nav.id}`);
    button.innerHTML = icon("M4 7h16M4 12h16M4 17h16");
    header.appendChild(button);
    bindCollapseFallback(button, nav);

    nav.querySelectorAll("a[href]").forEach((link) => {
      const href = link.getAttribute("href") || "";
      if (href === pathname || (pathname.startsWith("/docs/") && href === "/developer-docs")) {
        link.classList.add("active");
        link.setAttribute("aria-current", "page");
      }
    });
  }

  function addSkipLink() {
    if (document.querySelector(".skip-link, .nexora-skip-link")) return;
    const main = document.querySelector("main");
    if (!main) return;
    main.id = main.id || "main-content";
    const skip = document.createElement("a");
    skip.className = "nexora-skip-link";
    skip.href = `#${main.id}`;
    skip.textContent = "Skip to main content";
    body.prepend(skip);
  }

  function enhanceDocs() {
    const layout = document.querySelector(".layout");
    const sidebar = layout && layout.querySelector(".sidebar");
    if (!layout || !sidebar) return;
    sidebar.id = "nexora-docs-sidebar";
    sidebar.classList.add("hs-collapse", "hidden");
    sidebar.setAttribute("aria-label", "Documentation sections");

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "nexora-docs-toggle";
    toggle.setAttribute("data-hs-collapse", "#nexora-docs-sidebar");
    toggle.setAttribute("aria-controls", "nexora-docs-sidebar");
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = `${icon("M4 6h16M4 12h16M4 18h10")}<span>Browse documentation</span>${icon("m9 18 6-6-6-6")}`;
    layout.insertBefore(toggle, sidebar);
    bindCollapseFallback(toggle, sidebar);

    sidebar.querySelectorAll("a[href]").forEach((link) => {
      if (link.getAttribute("href") === pathname) {
        link.classList.add("active");
        link.setAttribute("aria-current", "page");
      }
    });

    document.querySelectorAll(".doc pre").forEach((pre) => {
      if (pre.parentElement && pre.parentElement.classList.contains("nexora-code")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "nexora-code";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "nexora-copy-button";
      copy.setAttribute("aria-label", "Copy code");
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        const value = pre.innerText;
        try {
          await navigator.clipboard.writeText(value);
          copy.textContent = "Copied";
        } catch (_error) {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(pre);
          selection.removeAllRanges();
          selection.addRange(range);
          copy.textContent = "Selected";
        }
        window.setTimeout(() => { copy.textContent = "Copy"; }, 1600);
      });
      wrapper.appendChild(copy);
    });
  }

  function enhanceTables() {
    document.querySelectorAll("table").forEach((table) => {
      if (table.parentElement && table.parentElement.classList.contains("table-wrap")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "table-wrap";
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  body.dataset.nexoraSurface = pageGroup();
  normalizeBrandCopy();
  addSkipLink();
  document.querySelectorAll("header.topbar").forEach(enhanceTopbar);
  enhanceDocs();
  enhanceTables();

  if (window.HSStaticMethods && typeof window.HSStaticMethods.autoInit === "function") {
    window.HSStaticMethods.autoInit();
  }
})();
