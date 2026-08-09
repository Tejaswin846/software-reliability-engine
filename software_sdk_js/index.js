const FRAMEWORKS = new Set([
  "openai-agents", "langgraph", "langchain", "crewai", "google-adk",
  "microsoft-agent-framework", "anthropic-agent-sdk", "pydantic-ai",
  "llamaindex", "mastra", "strands", "mcp", "temporal"
]);

export class MatrixsReliability {
  constructor({ apiUrl, apiKey, timeoutMs = 10000, redactionActions = {} }) {
    this.apiUrl = String(apiUrl || "").replace(/\/$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
    this.redactionActions = redactionActions;
    if (!this.apiUrl || !this.apiKey) throw new Error("apiUrl and apiKey are required");
  }

  async request(path, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.apiUrl}${path}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-software-api-key": this.apiKey
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(`Matrixs rejected telemetry: ${response.status}`);
      return result;
    } finally {
      clearTimeout(timer);
    }
  }

  observe(observation, options = {}) {
    return this.request("/api/sdk/v2/observations", {
      observation,
      source: "matrixs-js-sdk",
      framework: options.framework,
      redaction_actions: options.redactionActions || this.redactionActions,
      force_sample: Boolean(options.forceSample)
    });
  }

  ingestOTLP(payload, options = {}) {
    return this.request("/api/sdk/v2/telemetry/otel", {
      payload,
      redaction_actions: options.redactionActions || this.redactionActions
    });
  }

  ingestFramework(framework, event, options = {}) {
    const normalized = String(framework).toLowerCase().replaceAll("_", "-");
    if (!FRAMEWORKS.has(normalized)) throw new Error(`Unsupported Matrixs adapter: ${framework}`);
    return this.request(`/api/sdk/v2/adapters/${normalized}`, {
      payload: event,
      redaction_actions: options.redactionActions || this.redactionActions
    });
  }

  wrapTool(toolName, handler, metadata = {}) {
    return async (...args) => {
      const started = performance.now();
      try {
        const result = await handler(...args);
        await this.observe({
          type: "tool", name: toolName, tool_name: toolName, status: "success",
          latency_ms: performance.now() - started, ...metadata
        });
        return result;
      } catch (error) {
        await this.observe({
          type: "tool", name: toolName, tool_name: toolName, status: "error",
          error_type: error?.name || "Error", latency_ms: performance.now() - started,
          risk_score: 1, ...metadata
        }, { forceSample: true });
        throw error;
      }
    };
  }
}

export const supportedFrameworks = Object.freeze([...FRAMEWORKS]);
