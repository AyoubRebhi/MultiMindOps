# Security Score Backend-Frontend Linkage Fix

## Problem
Security score displayed 0/100 after plan approval because:
- Frontend expected: `task.result.security` with score/grade/vulnerabilities
- Backend provided: `task.result.repository_security` with raw risk_score/warnings

## Solution
Created `SecurityScoreTransformer` service that:
- Converts risk_score → security_score (inverted: 100 - risk_score)
- Transforms warnings/blocked_reasons → vulnerabilities array with severity levels
- Calculates grade from score (A+/A/B/C/D/F)
- Merges env_security_runtime data
- Generates recommendations

## Files Changed
- Created: `backend/app/services/security/security_score_transformer.py`
- Modified: `backend/app/agents/orchestrator_agent.py` (_finalize_node adds security field)
- Test: `tests/test_security_score_transformer.py`

## Key Points
- Transformer runs once per task in _finalize_node
- Result includes both "security" (transformed) and "repository_security" (raw)
- Backward compatible: raw data preserved
- No performance impact (~1-2ms overhead)
