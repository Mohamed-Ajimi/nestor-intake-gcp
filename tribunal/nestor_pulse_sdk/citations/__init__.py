"""Citation extraction + rendering (D-07 three-table model).

Public surface:
  - extract_and_persist_citations(provider_results, run_id, tenant_id, session)
      parses each provider's report into source + claim + claim_source rows.
  - router (renderer): FastAPI APIRouter mounted at /api/sources.

Per CONTEXT.md `<ui_import>` Data contracts: the UI fetches snapshot_text via
GET /api/sources/{id} and NEVER re-fetches the source URL. snapshot_text is
captured at fetch time so dead URLs don't break old reports.
"""

from nestor_pulse_sdk.citations.extractor import extract_and_persist_citations
from nestor_pulse_sdk.citations.renderer import router

__all__ = ["extract_and_persist_citations", "router"]
