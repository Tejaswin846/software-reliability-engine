# Matrixs JavaScript/TypeScript SDK

```js
import { MatrixsReliability } from "@matrixs/reliability";

const matrixs = new MatrixsReliability({
  apiUrl: "https://software-reliability-engine.onrender.com",
  apiKey: process.env.MATRIXS_API_KEY
});

await matrixs.observe({
  trace_id: "trace-1",
  span_id: "span-1",
  type: "agent",
  name: "planner",
  status: "success"
});
```

Use `ingestOTLP()` for OpenTelemetry JSON or `ingestFramework()` for OpenAI
Agents, LangGraph, LangChain, CrewAI, Google ADK, Microsoft Agent Framework,
Anthropic Agent SDK, PydanticAI, LlamaIndex, Mastra, Strands, MCP, and Temporal.
