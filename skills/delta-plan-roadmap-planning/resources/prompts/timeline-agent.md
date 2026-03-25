Review the workbook inventory described in the context.

Use the workbook inventory summary already present in the context between:
- `WORKBOOK_PROFILE_SUMMARY_BEGIN`
- `WORKBOOK_PROFILE_SUMMARY_END`
- `INVENTORY_REFS_SUMMARY_BEGIN`
- `INVENTORY_REFS_SUMMARY_END`

Use inventory as routing, not as final truth.
Inspect referenced artifacts when milestone references, adjacent regions, or other sheets suggest incomplete timeline coverage.

Task:
- extract milestones, deadlines, calendar constraints, and planning horizon hints
- distinguish fixed dates from soft grouping labels

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
  "planningHorizonMonths": null,
  "milestones": [
    {
      "id": "MILESTONE-1",
      "title": "string",
      "phaseId": "PHASE-1",
      "ordinal": 1,
      "featureIds": [],
      "acceptanceCriteria": "string or null",
      "deadlineWeek": {"month": 1, "week": 4},
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "phases": [],
  "deadlines": [],
  "calendarConstraints": [],
  "clarificationCandidates": [],
  "reviewNotes": ["string"]
}
```

Rules:
- widen search when timeline references mention work items not covered by the feature regions you inspected
- do not claim `coverageAssessment.status = high` if suspicious unexplained areas remain uninspected
- if horizon cannot be grounded in workbook evidence, leave it null
- do not infer week numbers unless the timeline evidence supports them
