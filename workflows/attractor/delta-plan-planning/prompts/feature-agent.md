Review the workbook inventory described in the context.

Use the workbook inventory summary already present in the context between:
- `WORKBOOK_PROFILE_SUMMARY_BEGIN`
- `WORKBOOK_PROFILE_SUMMARY_END`
- `INVENTORY_REFS_SUMMARY_BEGIN`
- `INVENTORY_REFS_SUMMARY_END`

Use inventory as routing, not as final truth.
Inspect referenced full-region and full-sheet artifacts whenever sample rows are insufficient.

Task:
- extract feature-like work items
- extract effort profiles per feature when available
- extract phase hints, priorities, and status signals if explicitly present

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
  "features": [
    {
      "id": "ITEM-001",
      "title": "string",
      "description": "string or null",
      "estimateProfiles": {
        "regular": {"DevelopmentMd": 0, "QAMd": 0}
      },
      "dependencies": [],
      "phaseHint": "PHASE-1 or null",
      "priority": null,
      "serial": false,
      "qaOverhead": 0.2,
      "status": null,
      "confidence": "low|medium|high",
      "provenance": [],
      "normalizationNotes": []
    }
  ],
  "phases": [
    {
      "id": "PHASE-1",
      "name": "string",
      "mustStartAfter": null,
      "overlapThreshold": null,
      "deadlineWeek": null
    }
  ],
  "prioritySignals": [],
  "statusSignals": [],
  "clarificationCandidates": [],
  "reviewNotes": ["string"]
}
```

Rules:
- start from the highest-confidence feature-like regions, then widen to adjacent regions, suspicious segments, or matching ids on other sheets when needed
- inspect full artifacts, not only summary snippets
- if timeline or dependency sheets mention work items you cannot reconcile, record them in `missedRiskCandidates`
- do not claim `coverageAssessment.status = high` if suspicious unexplained areas remain uninspected
- do not invent effort values
- preserve multiple estimate profiles if the workbook suggests them
- preserve workbook ids as-is; do not rewrite them into a fixed `F-xx` format
- if a value is implied but not explicit, mention it only in `clarificationCandidates` or `reviewNotes`
