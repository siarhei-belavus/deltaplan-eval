Review the workbook inventory described in the context.

Use the workbook inventory summary already present in the context between:
- `WORKBOOK_PROFILE_SUMMARY_BEGIN`
- `WORKBOOK_PROFILE_SUMMARY_END`
- `INVENTORY_REFS_SUMMARY_BEGIN`
- `INVENTORY_REFS_SUMMARY_END`

Use inventory as routing, not as final truth.
Inspect the referenced full-sheet or full-region artifacts when coverage would otherwise be incomplete.

Task:
- classify workbook regions into planning-relevant buckets
- identify which regions are likely feature tables, timeline tables, capacity tables, assumption lists, note blocks, or unknown
- identify ambiguity that should become clarification later

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
  "sheetClassifications": [
    {
      "sheetName": "string",
      "sheetRole": "features|timeline|capacity|assumptions|mixed|unknown",
      "confidence": "low|medium|high",
      "provenance": []
    }
  ],
  "regionClassifications": [
    {
      "regionId": "string",
      "regionRole": "feature_table|timeline_table|capacity_table|assumptions_list|notes|unknown",
      "confidence": "low|medium|high",
      "reason": "string",
      "provenance": []
    }
  ],
  "clarificationCandidates": [
    {
      "fieldPath": "schedule.someField",
      "prompt": "string",
      "reason": "string",
      "provenance": []
    }
  ],
  "reviewNotes": ["string"]
}
```

Rules:
- start from the inventory refs, then inspect full artifacts as needed
- widen search when adjacent regions, suspicious segments, or cross-sheet ids suggest incompleteness
- do not claim `coverageAssessment.status = high` if suspicious unexplained areas remain uninspected
- use only facts supported by workbook evidence
- keep provenance tied to sheet and range
- if unsure, lower confidence instead of guessing
