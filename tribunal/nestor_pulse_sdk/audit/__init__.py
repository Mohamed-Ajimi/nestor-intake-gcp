"""
nestor_pulse_sdk.audit -- tamper-evident audit pipeline (Plans 07 + 09).

Exports:
  - hash_chain:           canonical_json, link_hash, GENESIS, IN_FLIGHT_PLACEHOLDER, verify_chain
  - cost_table:           compute(provider, model, prompt_tokens, completion_tokens, cached_tokens)
  - gcs_blob:             upload_audit_body(...)
  - audited_llm_client:   AuditedLLMClient, AuditHandle
  - writer:               DBAuditWriter (DB-backed audit_log writer)
  - build_audited_client: factory wiring the production AuditedLLMClient

Design decisions (D-11/D-12/D-13):
  - Metadata in Postgres audit_log; full bodies in GCS with per-object retention.
  - SHA-256 hash chain per run; GENESIS = "0"*64.
  - verify_chain is server-side ONLY (D-13 + Anti-pattern line 585).
  - AuditedLLMClient exposes BOTH atomic-call AND two-phase (start_call/end_call) APIs.
"""
from __future__ import annotations

import os
from typing import Optional

from nestor_pulse_sdk.audit.hash_chain import (
    GENESIS,
    IN_FLIGHT_PLACEHOLDER,
    canonical_json,
    link_hash,
    verify_chain,
)
from nestor_pulse_sdk.audit.audited_llm_client import (
    AuditedLLMClient,
    AuditHandle,
    build_audited_client,
)
from nestor_pulse_sdk.audit.writer import DBAuditWriter


__all__ = [
    "GENESIS",
    "IN_FLIGHT_PLACEHOLDER",
    "AuditedLLMClient",
    "AuditHandle",
    "DBAuditWriter",
    "build_audited_client",
    "canonical_json",
    "link_hash",
    "verify_chain",
]
