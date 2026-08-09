export type RedactionAction = "drop" | "mask" | "hash" | "tokenize" | "allow";
export interface MatrixsOptions {
  apiUrl: string;
  apiKey: string;
  timeoutMs?: number;
  redactionActions?: Record<string, RedactionAction>;
}
export interface ObservationOptions {
  framework?: string;
  redactionActions?: Record<string, RedactionAction>;
  forceSample?: boolean;
}
export declare class MatrixsReliability {
  constructor(options: MatrixsOptions);
  observe(observation: Record<string, unknown>, options?: ObservationOptions): Promise<unknown>;
  ingestOTLP(payload: Record<string, unknown>, options?: ObservationOptions): Promise<unknown>;
  ingestFramework(framework: string, event: Record<string, unknown>, options?: ObservationOptions): Promise<unknown>;
  wrapTool<T extends (...args: any[]) => any>(toolName: string, handler: T, metadata?: Record<string, unknown>): T;
}
export declare const supportedFrameworks: readonly string[];
