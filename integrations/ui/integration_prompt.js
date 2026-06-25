(function () {
  function ensurePrompt() {
    let prompt = document.getElementById("software-app-connect-prompt");
    if (prompt) return prompt;
    prompt = document.createElement("div");
    prompt.id = "software-app-connect-prompt";
    prompt.hidden = true;
    prompt.innerHTML = `
      <div class="software-app-prompt-backdrop"></div>
      <section class="software-app-prompt-card" role="dialog" aria-modal="true">
        <h2 id="software-app-prompt-title">Connect app?</h2>
        <p id="software-app-prompt-message"></p>
        <div class="software-app-prompt-actions">
          <button type="button" data-app-prompt-cancel>Not now</button>
          <button type="button" data-app-prompt-connect>Connect</button>
        </div>
      </section>
    `;
    const style = document.createElement("style");
    style.textContent = `
      #software-app-connect-prompt[hidden]{display:none}
      #software-app-connect-prompt{position:fixed;inset:0;z-index:1000;font-family:Inter,system-ui,sans-serif}
      .software-app-prompt-backdrop{position:absolute;inset:0;background:rgba(14,23,19,.48)}
      .software-app-prompt-card{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(420px,calc(100% - 32px));background:#fff;border:1px solid #dfe6e2;border-radius:8px;padding:22px;color:#17211c}
      .software-app-prompt-card h2{margin:0 0 8px;font-size:20px}
      .software-app-prompt-card p{color:#64736b;line-height:1.5;margin:0 0 20px}
      .software-app-prompt-actions{display:flex;justify-content:flex-end;gap:9px}
      .software-app-prompt-actions button{border:1px solid #167a5b;border-radius:8px;padding:9px 13px;font:inherit;font-weight:800;cursor:pointer}
      [data-app-prompt-cancel]{background:#fff;color:#167a5b}
      [data-app-prompt-connect]{background:#167a5b;color:#fff}
      .software-app-toast{position:fixed;right:18px;bottom:18px;z-index:1001;background:#17211c;color:#fff;border-radius:8px;padding:12px 15px;max-width:360px;font:600 14px Inter,system-ui,sans-serif}
    `;
    document.head.appendChild(style);
    document.body.appendChild(prompt);
    return prompt;
  }

  function toast(message) {
    const element = document.createElement("div");
    element.className = "software-app-toast";
    element.textContent = message;
    document.body.appendChild(element);
    window.setTimeout(() => element.remove(), 5000);
  }

  async function requestConnection(details) {
    const prompt = ensurePrompt();
    const app = details.app || {};
    document.getElementById("software-app-prompt-title").textContent =
      `This action requires ${app.name || "an app"}.`;
    document.getElementById("software-app-prompt-message").textContent =
      `Connect ${app.name || "the app"}? After authorization, Software will return here and continue the request.`;
    prompt.hidden = false;

    return new Promise((resolve) => {
      const cancel = prompt.querySelector("[data-app-prompt-cancel]");
      const connect = prompt.querySelector("[data-app-prompt-connect]");
      const cleanup = () => {
        cancel.onclick = null;
        connect.onclick = null;
        prompt.hidden = true;
      };
      cancel.onclick = () => {
        cleanup();
        resolve(false);
      };
      connect.onclick = async () => {
        connect.disabled = true;
        connect.textContent = "Opening...";
        try {
          const response = await fetch("/api/integrations/connect", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({
              app_id: app.id,
              pending_action_id: details.pending_action_id,
              return_to: window.location.pathname + window.location.search,
            }),
          });
          const body = await response.json();
          if (!response.ok || !body.redirect_url) {
            throw new Error(body.detail || "The app could not be connected.");
          }
          window.location.href = body.redirect_url;
        } catch (error) {
          connect.disabled = false;
          connect.textContent = "Connect";
          toast(error.message);
        }
      };
    });
  }

  async function resumeFromQuery() {
    const query = new URLSearchParams(window.location.search);
    const resumeId = query.get("resume_id");
    if (!resumeId) return;
    try {
      const response = await fetch(`/api/integrations/resume/${encodeURIComponent(resumeId)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const body = await response.json();
      if (response.ok && body.resume) {
        const success = body.resume.status === "completed";
        toast(success ? "App connected. Your original request continued." : "App connected. The original action needs attention.");
        window.dispatchEvent(
          new CustomEvent("software:integration-resumed", { detail: body.resume }),
        );
      }
    } catch (_) {
      toast("The app connected, but the original action status could not be loaded.");
    } finally {
      query.delete("resume_id");
      query.delete("integration_connected");
      query.delete("integration_resumed");
      const clean = `${window.location.pathname}${query.toString() ? `?${query}` : ""}${window.location.hash}`;
      window.history.replaceState({}, "", clean);
    }
  }

  window.SoftwareApps = {
    requireConnection: requestConnection,
    toast,
  };

  document.addEventListener("DOMContentLoaded", () => {
    ensurePrompt();
    resumeFromQuery();
  });
})();
