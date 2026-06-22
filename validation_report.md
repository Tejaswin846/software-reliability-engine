# Phase 12 Real-World Validation Report

Generated: 2026-06-20T19:25:21.014393+05:30

## Configuration

- Total workflows: 500
- Models: llama3.2:3b, qwen2.5:3b
- Benchmark suites: Research Tasks, Retrieval Tasks, Multi-Step Agent Tasks, Search + Extract Tasks
- Ollama endpoint: `http://127.0.0.1:11434`
- Ollama timeout: 45.0s
- Ollama output tokens per call: 4
- Guardrail failure threshold: 0.55
- Elapsed time: 1678.72s

## Overall Comparison

| Mode | Reliability Score | Success Rate | Failure Rate | Prediction Accuracy | Guardrail Recovery | Avg Time | Avg Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 88.52 | 85.60% | 14.40% | 97.80% | 0.00% | 4058.40ms | 0.866 |
| prediction_enabled | 88.52 | 85.60% | 14.40% | 97.80% | 0.00% | 4058.40ms | 0.866 |
| guardrail_enabled | 89.25 | 94.80% | 5.20% | 97.80% | 75.41% | 4122.40ms | 0.866 |

## By Model

### baseline

| Model | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| llama3.2:3b | 85.31 | 84.00% | 16.00% | 97.20% | 0.00% |
| qwen2.5:3b | 91.65 | 87.20% | 12.80% | 98.40% | 0.00% |

### prediction_enabled

| Model | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| llama3.2:3b | 85.31 | 84.00% | 16.00% | 97.20% | 0.00% |
| qwen2.5:3b | 91.65 | 87.20% | 12.80% | 98.40% | 0.00% |

### guardrail_enabled

| Model | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| llama3.2:3b | 89.91 | 94.40% | 5.60% | 97.20% | 78.79% |
| qwen2.5:3b | 88.52 | 95.20% | 4.80% | 98.40% | 71.43% |

## By Benchmark Suite

### baseline

| Suite | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| Research Tasks | 85.07 | 84.00% | 16.00% | 97.60% | 0.00% |
| Retrieval Tasks | 96.03 | 93.60% | 6.40% | 98.40% | 0.00% |
| Multi-Step Agent Tasks | 85.56 | 84.00% | 16.00% | 96.80% | 0.00% |
| Search + Extract Tasks | 78.63 | 80.80% | 19.20% | 98.40% | 0.00% |

### prediction_enabled

| Suite | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| Research Tasks | 85.07 | 84.00% | 16.00% | 97.60% | 0.00% |
| Retrieval Tasks | 96.03 | 93.60% | 6.40% | 98.40% | 0.00% |
| Multi-Step Agent Tasks | 85.56 | 84.00% | 16.00% | 96.80% | 0.00% |
| Search + Extract Tasks | 78.63 | 80.80% | 19.20% | 98.40% | 0.00% |

### guardrail_enabled

| Suite | Score | Success | Failure | Prediction Accuracy | Guardrail Recovery |
| --- | --- | --- | --- | --- | --- |
| Research Tasks | 93.29 | 96.00% | 4.00% | 97.60% | 88.24% |
| Retrieval Tasks | 87.43 | 96.80% | 3.20% | 98.40% | 66.67% |
| Multi-Step Agent Tasks | 86.2 | 92.80% | 7.20% | 96.80% | 68.75% |
| Search + Extract Tasks | 87.98 | 93.60% | 6.40% | 98.40% | 72.73% |

## Failure Distribution

| Failure Stage | Count | Percentage |
| --- | --- | --- |
| search | 27 | 37.50% |
| extraction | 25 | 34.72% |
| reasoning | 11 | 15.28% |
| planning | 9 | 12.50% |

## Validation Conclusion

Baseline success was 85.60%. Prediction enabled measured failure risk with 97.80% accuracy. Guardrail enabled raised success to 94.80%, a 9.20 point improvement.

The Reliability Score moved from 88.52 to 89.25, a 0.73 point improvement under larger, more realistic workloads.

Raw validation data saved to `C:\Users\user\Desktop\Nexora ai\Software\data\real_world_validation_output.json`.
