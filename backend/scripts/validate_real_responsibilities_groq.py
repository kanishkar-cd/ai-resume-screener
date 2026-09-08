import asyncio
import json
import sys
from uuid import UUID
from sqlalchemy import select

# Fix Windows console utf-8 output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import AsyncSessionLocal
from app.models import (
    DocumentModel,
    DocumentTypeEnum,
    NormalizedJDModel,
    NormalizedResumeModel,
    ExtractedResumeModel,
    ExtractedJDModel,
    ProjectModel,
)
from app.services.matching_service import HybridMatchingService, EvidenceBuilder
from app.schemas.matching import RequirementKind, MatchStatus
from app.core.config import get_settings


async def validate_responsibilities_groq():
    settings = get_settings()
    # Ensure Hybrid Matching is enabled with real Groq
    print(f"Groq Model: {settings.GROQ_MODEL}")
    print(f"Groq API Key set: {bool(settings.GROQ_API_KEY)}")
    print(f"Enable Cerebras Fallback: {settings.ENABLE_CEREBRAS_FALLBACK}")

    hybrid = HybridMatchingService(settings=settings)

    # We will validate 5 diverse real resumes from project 7d66d7ac-5df4-490a-8dad-8fd65e6a9557
    project_id_str = "7d66d7ac-5df4-490a-8dad-8fd65e6a9557"

    results = []

    async with AsyncSessionLocal() as session:
        proj = (await session.execute(select(ProjectModel).where(ProjectModel.id == UUID(project_id_str)))).scalar_one_or_none()
        docs = (await session.execute(select(DocumentModel).where(DocumentModel.project_id == UUID(project_id_str)))).scalars().all()

        jd_doc = next(d for d in docs if d.document_type == DocumentTypeEnum.JOB_DESCRIPTION)
        norm_jd = (await session.execute(select(NormalizedJDModel).where(NormalizedJDModel.document_id == jd_doc.id))).scalar_one()
        ext_jd = (await session.execute(select(ExtractedJDModel).where(ExtractedJDModel.document_id == jd_doc.id))).scalar_one_or_none()

        resume_docs = [d for d in docs if d.document_type == DocumentTypeEnum.RESUME][:5]
        print(f"\n================================================================================")
        print(f"JOB: {norm_jd.job_title} ({proj.title})")
        print(f"EVALUATING {len(resume_docs)} REAL RESUMES FOR ROLES & RESPONSIBILITIES")
        print(f"================================================================================\n")

        for idx, r_doc in enumerate(resume_docs, 1):
            norm_r = (await session.execute(select(NormalizedResumeModel).where(NormalizedResumeModel.document_id == r_doc.id))).scalar_one_or_none()
            ext_r = (await session.execute(select(ExtractedResumeModel).where(ExtractedResumeModel.document_id == r_doc.id))).scalar_one_or_none()

            if not norm_r or not ext_r:
                continue

            cand_name = getattr(norm_r, "candidate_name", None) or r_doc.original_filename
            print(f"\n>>> Running Evaluation for Resume #{idx}: {cand_name} ({r_doc.original_filename})")

            # Execute full hybrid match
            reqs, verdicts = await hybrid.match(norm_jd, norm_r, ext_r)

            # Build candidate evidence map to verify IDs
            ev_list = EvidenceBuilder.build(ext_r)
            ev_map = {e.evidence_id: e for e in ev_list}
            valid_evidence_ids = set(ev_map.keys())

            # Filter for Responsibilities and Project Relevance
            resp_verdicts = [
                v for v in verdicts
                if v.kind in {RequirementKind.RESPONSIBILITY, RequirementKind.PROJECT_RELEVANCE}
            ]

            skill_verdicts = [
                v for v in verdicts
                if v.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL}
            ]

            resume_report = {
                "index": idx,
                "resume_id": str(r_doc.id),
                "candidate_name": cand_name,
                "filename": r_doc.original_filename,
                "responsibilities_evaluated": [],
                "eval_failed_count": 0,
                "hallucinated_evidence_count": 0,
            }

            print(f"--------------------------------------------------------------------------------")
            print(f"RESUME #{idx}: {cand_name}")
            print(f"--------------------------------------------------------------------------------")

            for v in resp_verdicts:
                # Check evidence validity
                ev_ids = v.evidence_ids or []
                invalid_ids = [eid for eid in ev_ids if eid not in valid_evidence_ids]
                is_hallucinated = len(invalid_ids) > 0

                ev_snippets = [ev_map[eid].text.replace("\n", " ").strip() for eid in ev_ids if eid in ev_map]
                ev_str = " | ".join(ev_snippets) if ev_snippets else "None"
                if len(ev_str) > 120:
                    ev_str = ev_str[:117] + "..."

                pts = v.coverage_score if v.coverage_score is not None else v.coverage
                is_failed = v.status == MatchStatus.EVALUATION_FAILED

                if is_failed:
                    resume_report["eval_failed_count"] += 1
                if is_hallucinated:
                    resume_report["hallucinated_evidence_count"] += 1

                print(f"  * Responsibility: {v.requirement_text}")
                print(f"    - Verdict:      {v.status.value} ({pts} pts) via {v.method}")
                print(f"    - Evidence IDs: {ev_ids} (All Valid: {not is_hallucinated})")
                print(f"    - Evidence:     {ev_str}")
                print(f"    - Reasoning:    {v.reasoning}")

                resume_report["responsibilities_evaluated"].append({
                    "requirement": v.requirement_text,
                    "verdict": v.status.value,
                    "points": float(pts or 0.0),
                    "method": v.method.value if v.method else "none",
                    "evidence_ids": ev_ids,
                    "evidence_text": ev_str,
                    "is_valid_evidence": not is_hallucinated,
                    "reasoning": v.reasoning,
                })

            # Calculate total responsibility score (0-100)
            if resp_verdicts:
                total_pts = sum(float(getattr(v, "coverage_score", 0.0) or 0.0) for v in resp_verdicts)
                resp_score = round((total_pts / len(resp_verdicts)) * 100.0, 1)
            else:
                resp_score = 0.0

            resume_report["final_responsibility_score"] = resp_score
            print(f"\n  >> Final Responsibility Score: {resp_score}%")
            print(f"  >> Evaluation Failed Count: {resume_report['eval_failed_count']}")
            print(f"  >> Hallucinated Evidence Count: {resume_report['hallucinated_evidence_count']}")

            results.append(resume_report)

            # Pacing delay between resumes to respect TPM budget
            await asyncio.sleep(2.0)

    with open("real_responsibilities_groq_validation.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n================================================================================")
    print(f"VALIDATION FINISHED: Evaluated {len(results)} resumes successfully.")
    print(f"================================================================================")
    return results


if __name__ == "__main__":
    asyncio.run(validate_responsibilities_groq())
