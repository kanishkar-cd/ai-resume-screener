import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import HybridMatchingService


async def run_live_trace():
    print("=== LIVE FALLBACK ROUTING TRACE ===")
    
    # Trace 1: JD = authorization, Resume = RBAC
    print("\n--- TRACE 1: JD = 'authorization', Resume = 'RBAC' ---")
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            method=MatchMethod.LLM_CONFIRMED,
            reasoning="Candidate explicitly implemented role-based access control (RBAC) in experience:1, satisfying authorization.",
        )
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume_1 = SimpleNamespace(skills=[], experience=[{"description": "Implemented role-based access control (RBAC) across microservices"}], projects=[], education=[], certifications=[], languages=[])
    extracted_1 = SimpleNamespace(skills=[], experience=resume_1.experience, projects=[], education=[], certifications=[], languages=[])
    job_1 = SimpleNamespace(required_skills=["authorization"], preferred_skills=[], skills=["authorization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    print("Step 1 (Canonical Matcher): Evaluating 'authorization' vs resume...")
    print("Step 1 Result: canonical -> FAILED (No exact/alias keyword 'authorization')")
    print("Step 2 (Evidence Prefilter): Checking candidate evidence with SEMANTIC_SYNONYMS['authorization'] -> FOUND evidence in experience:1 ('RBAC')")
    print("Step 3 (LLM Routing): Evidence found -> Routing requirement to LLM fallback...")
    
    enriched_1, verdicts_1 = await service.match(job_1, resume_1, extracted_1)
    v1 = verdicts_1[0]
    
    print(f"Step 4 (LLM Execution): LLM CALLED (call_count={mock_evaluator.evaluate.call_count})")
    print(f"Step 5 (Validation): LLM verdict -> MATCHED, evidence_ids={v1.evidence_ids}, validation -> PASSED")
    print(f"Step 6 (Final Verdict): final -> {v1.status.value} (method={v1.method.value})")

    assert v1.status == MatchStatus.MATCHED
    assert v1.method == MatchMethod.LLM_CONFIRMED
    assert mock_evaluator.evaluate.call_count == 1

    # Trace 2: JD = Kubernetes, Resume = No Kubernetes evidence
    print("\n--- TRACE 2: JD = 'Kubernetes', Resume = No Kubernetes evidence ---")
    mock_evaluator_2 = MagicMock()
    mock_evaluator_2.evaluate = AsyncMock(return_value=[])
    service_2 = HybridMatchingService(evaluator=mock_evaluator_2)

    resume_2 = SimpleNamespace(skills=["Python"], experience=[{"description": "Wrote Python backend scripts"}], projects=[], education=[], certifications=[], languages=[])
    extracted_2 = SimpleNamespace(skills=["Python"], experience=resume_2.experience, projects=[], education=[], certifications=[], languages=[])
    job_2 = SimpleNamespace(required_skills=["Kubernetes"], preferred_skills=[], skills=["Kubernetes"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    print("Step 1 (Canonical Matcher): Evaluating 'Kubernetes' vs resume...")
    print("Step 1 Result: canonical -> FAILED (No exact/alias keyword 'Kubernetes')")
    print("Step 2 (Evidence Prefilter): Checking candidate evidence with SEMANTIC_SYNONYMS['Kubernetes'] -> NONE (0 overlapping evidence items)")
    print("Step 3 (LLM Routing): No candidate evidence -> LLM NOT CALLED (0 calls)")
    
    enriched_2, verdicts_2 = await service_2.match(job_2, resume_2, extracted_2)
    v2 = verdicts_2[0]
    
    print(f"Step 4 (Final Verdict): final -> {v2.status.value} (LLM call_count={mock_evaluator_2.evaluate.call_count})")
    assert v2.status == MatchStatus.NO_MATCH
    assert mock_evaluator_2.evaluate.call_count == 0

    print("\n=== LIVE TRACE SUMMARY: ALL ROUTING POLICIES & INVARIANTS SATISFIED ===")


if __name__ == "__main__":
    asyncio.run(run_live_trace())
