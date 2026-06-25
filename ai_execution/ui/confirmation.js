(function () {
  let activeReview = null;

  function ensureCard() {
    let root = document.getElementById("software-ai-confirmation");
    if (root) return root;
    root = document.createElement("div");
    root.id = "software-ai-confirmation";
    root.hidden = true;
    root.innerHTML = `
      <div class="software-ai-confirmation-backdrop"></div>
      <section class="software-ai-confirmation-card" role="dialog" aria-modal="true" aria-labelledby="software-ai-confirmation-title">
        <p class="software-ai-confirmation-eyebrow">Human confirmation required</p>
        <h2 id="software-ai-confirmation-title">Review before running</h2>
        <dl>
          <div><dt>Action</dt><dd data-confirmation-action></dd></div>
          <div><dt>Target app</dt><dd data-confirmation-app></dd></div>
          <div><dt>Recipient / target</dt><dd data-confirmation-target></dd></div>
          <div><dt>Data affected</dt><dd data-confirmation-data></dd></div>
          <div class="risk"><dt>Possible risk</dt><dd data-confirmation-risk></dd></div>
        </dl>
        <p class="software-ai-confirmation-error" data-confirmation-error hidden></p>
        <div class="software-ai-confirmation-actions">
          <button type="button" data-confirmation-cancel>Cancel</button>
          <button type="button" data-confirmation-confirm>Confirm</button>
        </div>
      </section>
    `;
    const style = document.createElement("style");
    style.textContent = `
      #software-ai-confirmation[hidden]{display:none}
      #software-ai-confirmation{position:fixed;inset:0;z-index:1100;font-family:Inter,system-ui,sans-serif}
      .software-ai-confirmation-backdrop{position:absolute;inset:0;background:rgba(14,23,19,.58)}
      .software-ai-confirmation-card{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(520px,calc(100% - 32px));max-height:calc(100vh - 32px);overflow:auto;background:#fff;border:1px solid #dfe6e2;border-radius:8px;padding:24px;color:#17211c;box-shadow:0 24px 70px rgba(15,31,23,.2)}
      .software-ai-confirmation-eyebrow{margin:0 0 5px;color:#a76208;font-size:12px;font-weight:800;text-transform:uppercase}
      .software-ai-confirmation-card h2{margin:0 0 18px;font-size:22px}
      .software-ai-confirmation-card dl{display:grid;gap:10px;margin:0}
      .software-ai-confirmation-card dl div{display:grid;grid-template-columns:132px 1fr;gap:12px;border-bottom:1px solid #edf1ef;padding:0 0 10px}
      .software-ai-confirmation-card dl div.risk{background:#fff2d7;border:1px solid #f0d89f;border-radius:8px;padding:12px}
      .software-ai-confirmation-card dt{color:#64736b;font-size:12px;font-weight:800}
      .software-ai-confirmation-card dd{margin:0;font-size:14px;font-weight:650;overflow-wrap:anywhere}
      .software-ai-confirmation-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
      .software-ai-confirmation-actions button{border:1px solid #167a5b;border-radius:8px;padding:10px 15px;font:inherit;font-weight:850;cursor:pointer}
      [data-confirmation-cancel]{background:#fff;color:#167a5b}
      [data-confirmation-confirm]{background:#167a5b;color:#fff}
      .software-ai-confirmation-actions button:disabled{cursor:wait;opacity:.6}
      .software-ai-confirmation-error{background:#fde8e6;border:1px solid #f7c0bb;border-radius:8px;color:#b42318;margin:14px 0 0;padding:10px;font-size:13px}
      @media(max-width:560px){.software-ai-confirmation-card dl div{grid-template-columns:1fr;gap:4px}.software-ai-confirmation-actions{flex-direction:column-reverse}.software-ai-confirmation-actions button{width:100%}}
    `;
    document.head.appendChild(style);
    document.body.appendChild(root);
    return root;
  }

  async function post(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      const error = new Error(body.error || body.detail || `Request failed: ${response.status}`);
      error.body = body;
      throw error;
    }
    return body;
  }

  function setText(root, selector, value) {
    const element = root.querySelector(selector);
    if (element) element.textContent = value || "Not specified";
  }

  function requestConfirmation(details) {
    if (activeReview) return activeReview;
    const root = ensureCard();
    const card = details.confirmation_card || {};
    const requestId = details.request_id || card.request_id;
    setText(root, "[data-confirmation-action]", card.action);
    setText(root, "[data-confirmation-app]", card.target_app);
    setText(root, "[data-confirmation-target]", card.recipient_or_target);
    setText(root, "[data-confirmation-data]", card.data_affected);
    setText(root, "[data-confirmation-risk]", card.possible_risk);
    const errorElement = root.querySelector("[data-confirmation-error]");
    const cancel = root.querySelector("[data-confirmation-cancel]");
    const confirm = root.querySelector("[data-confirmation-confirm]");
    errorElement.hidden = true;
    root.hidden = false;

    activeReview = new Promise((resolve) => {
      const cleanup = () => {
        cancel.onclick = null;
        confirm.onclick = null;
        cancel.disabled = false;
        confirm.disabled = false;
        confirm.textContent = "Confirm";
        root.hidden = true;
        activeReview = null;
      };
      cancel.onclick = async () => {
        cancel.disabled = true;
        confirm.disabled = true;
        try {
          const result = await post("/api/ai/confirm", {
            request_id: requestId,
            decision: "cancel",
          });
          cleanup();
          window.dispatchEvent(new CustomEvent("software:ai-execution-cancelled", { detail: result }));
          resolve(result);
        } catch (error) {
          errorElement.textContent = error.message;
          errorElement.hidden = false;
          cancel.disabled = false;
          confirm.disabled = false;
        }
      };
      confirm.onclick = async () => {
        cancel.disabled = true;
        confirm.disabled = true;
        confirm.textContent = "Running...";
        try {
          await post("/api/ai/confirm", {
            request_id: requestId,
            decision: "confirm",
          });
          const result = window.SoftwareAuth?.request
            ? await window.SoftwareAuth.request("/api/ai/execute", {
                method: "POST",
                body: JSON.stringify({ request_id: requestId }),
              })
            : await post("/api/ai/execute", { request_id: requestId });
          cleanup();
          const eventName = result.connection_required
            ? "software:ai-execution-awaiting-connection"
            : "software:ai-execution-completed";
          window.dispatchEvent(new CustomEvent(eventName, { detail: result }));
          resolve(result);
        } catch (error) {
          if (error.response?.status === "failed") {
            const result = error.response;
            cleanup();
            window.dispatchEvent(new CustomEvent("software:ai-execution-failed", { detail: result }));
            resolve(result);
            return;
          }
          errorElement.textContent = error.message;
          errorElement.hidden = false;
          cancel.disabled = false;
          confirm.disabled = false;
          confirm.textContent = "Confirm";
        }
      };
    });
    return activeReview;
  }

  window.SoftwareAI = {
    requestConfirmation,
  };

  document.addEventListener("DOMContentLoaded", ensureCard);
})();
