Review the workbook inventory described in the context.

Use the workbook inventory summary already present in the context between:
- `WORKBOOK_PROFILE_SUMMARY_BEGIN`
- `WORKBOOK_PROFILE_SUMMARY_END`
- `INVENTORY_REFS_SUMMARY_BEGIN`
- `INVENTORY_REFS_SUMMARY_END`

Use inventory as routing, not as final truth.
Inspect full artifacts when summary hints are too weak to justify capacity extraction.

Task:
- extract roles and any explicit monthly or weekly capacity allocations
- separate explicit capacity facts from hints or notes that still require clarification

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
  "roles": [
    {
      "name": "Development",
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "capacities": [
    {
      "month": 1,
      "roleFtes": {"Development": 1.0, "QA": 1.0},
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "clarificationCandidates": [
    {
      "fieldPath": "schedule.monthlyCapacity",
      "prompt": "string",
      "reason": "string",
      "provenance": []
    }
  ],
  "reviewNotes": ["string"]
}
```

Rules:
- widen search when suspicious segments or cross-sheet references suggest capacity facts may live outside the first region
- do not claim `coverageAssessment.status = high` if suspicious unexplained areas remain uninspected
- do not guess capacity from effort
- if there is no explicit capacity table, prefer a clarification candidate over a fabricated value
