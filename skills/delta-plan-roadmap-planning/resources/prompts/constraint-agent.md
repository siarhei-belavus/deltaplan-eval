Review the workbook inventory described in the context.

Use the workbook inventory summary already present in the context between:
- `WORKBOOK_PROFILE_SUMMARY_BEGIN`
- `WORKBOOK_PROFILE_SUMMARY_END`
- `INVENTORY_REFS_SUMMARY_BEGIN`
- `INVENTORY_REFS_SUMMARY_END`

Use inventory as routing, not as final truth.
Inspect referenced artifacts when dependency evidence is incomplete or conflicts across sheets.

Task:
- extract dependencies, assumptions, blockers, risk signals, and sequencing constraints

Return exactly one JSON object and nothing else:

```json
{
  "summary": "short summary",
  "usedRegions": [],
  "expandedSearch": [],
  "ignoredRegions": [],
  "coverageAssessment": {
    "status": "high|medium|low",
    "reason": "string"
  },
  "missedRiskCandidates": [],
  "dependencies": [
    {
      "featureId": "ITEM-002",
      "dependsOn": ["ITEM-001"],
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "constraints": [
    {
      "type": "string",
      "summary": "string",
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "assumptions": [
    {
      "id": "ASSUMPTION-1",
      "text": "string",
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "riskSignals": [],
  "clarificationCandidates": [],
  "reviewNotes": ["string"]
}
```

Rules:
- widen search when ids appear across sheets or a region mixes work items with totals, notes, or schedule rows
- do not claim `coverageAssessment.status = high` if suspicious unexplained areas remain uninspected
- keep assumptions and constraints separate
- preserve workbook ids as-is; do not normalize them to a fixed naming convention
- if a dependency is ambiguous, lower confidence or turn it into a clarification candidate
