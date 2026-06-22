async function submitRequestAccess(event) {
  event.preventDefault();
  const form = event.target;
  const message = document.getElementById("request-access-message");
  const payload = {
    name: form.name.value,
    email: form.email.value,
    company: form.company.value || null,
    role: form.role.value || null,
    use_case: form.use_case.value,
    expected_workflows_per_month: form.expected_workflows_per_month.value
      ? Number(form.expected_workflows_per_month.value)
      : null,
    timeline: form.timeline.value || null,
  };
  message.className = "form-message";
  message.textContent = "Submitting...";
  try {
    const response = await fetch("/api/request-access", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.detail || body.message || "Request failed");
    }
    form.reset();
    message.className = "form-message success";
    message.textContent = "Request received. We will follow up with early access details.";
  } catch (error) {
    message.className = "form-message error";
    message.textContent = error.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("request-access-form");
  if (form) {
    form.addEventListener("submit", submitRequestAccess);
  }
});
