## Response format

You MUST respond with a single JSON object inside a fenced code block tagged `json`. No prose before or after the fence. Schema:

```json
{
  "verdict": "BUY" | "SELL" | "SKIP",
  "confidence": <decimal between 0 and 1>,
  "p_win": <decimal between 0 and 1>,
  "rationale": "<one to three sentences explaining your reasoning>"
}
```

Field rules:
- `verdict`: BUY if the YES outcome is mispriced low; SELL if mispriced high; SKIP when uncertain or the evidence does not support a directional bet.
- `confidence`: how strongly you hold the verdict (0 = no opinion, 1 = certain). Calibrate honestly — over-confident calls degrade portfolio P&L.
- `p_win`: your estimated true probability that the YES outcome resolves YES.
- `rationale`: tight, factual. Cite the specific evidence (numbers, news, base rates) that drove the call.

Return only the JSON block. No commentary, no extra fields, no nesting.
