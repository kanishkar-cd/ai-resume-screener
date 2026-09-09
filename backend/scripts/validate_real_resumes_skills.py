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
from app.core.config import Settings


def make_deterministic_settings():
    return Settings(
        GROQ_API_KEY="",  # 0 Groq calls for skills validation
        CEREBRAS_API_KEY="",
        ENABLE_HYBRID_MATCHING=False,
    )


async def validate_real_resumes():
    settings = make_deterministic_settings()
    hybrid = HybridMatchingService(settings=settings)

    target_projects = [
        "7d66d7ac-5df4-490a-8dad-8fd65e6a9557",
        "2664bd71-5a48-4aa8-880a-ea83c5e655a5",
    ]

    all_resumes_data = []

    async with AsyncSessionLocal() as session:
        for p_id in target_projects:
            proj = (await session.execute(select(ProjectModel).where(ProjectModel.id == UUID(p_id)))).scalar_one_or_none()
            if not proj:
                continue

            docs = (await session.execute(select(DocumentModel).where(DocumentModel.project_id == UUID(p_id)))).scalars().all()
            jd_doc = next((d for d in docs if d.document_type == DocumentTypeEnum.JOB_DESCRIPTION), None)
            if not jd_doc:
                continue

            norm_jd = (await session.execute(select(NormalizedJDModel).where(NormalizedJDModel.document_id == jd_doc.id))).scalar_one_or_none()
            ext_jd = (await session.execute(select(ExtractedJDModel).where(ExtractedJDModel.document_id == jd_doc.id))).scalar_one_or_none()

            resume_docs = [d for d in docs if d.document_type == DocumentTypeEnum.RESUME]
            print(f"\n================================================================================")
            print(f"PROJECT: {proj.title} (ID: {p_id})")
            req_skills = getattr(norm_jd, "required_skills", []) or []
            print(f"REQUIRED HARD SKILLS ({len(req_skills)}): {req_skills}")
            print(f"================================================================================\n")

            for r_doc in resume_docs:
                norm_r = (await session.execute(select(NormalizedResumeModel).where(NormalizedResumeModel.document_id == r_doc.id))).scalar_one_or_none()
                ext_r = (await session.execute(select(ExtractedResumeModel).where(ExtractedResumeModel.document_id == r_doc.id))).scalar_one_or_none()

                if not norm_r or not ext_r:
                    continue

                # Run matching
                reqs, verdicts = await hybrid.match(norm_jd, norm_r, ext_r)

                ev_list = EvidenceBuilder.build(ext_r)
                ev_map = {e.evidence_id: e for e in ev_list}

                # Filter strictly for Required Skills
                skill_verdicts = [
                    v for v in verdicts
                    if v.kind in {RequirementKind.SKILL, RequirementKind.REQUIRED_SKILL}
                ]

                cand_name = getattr(norm_r, "candidate_name", None) or r_doc.original_filename
                cand_record = {
                    "resume_id": str(r_doc.id),
                    "candidate_name": cand_name,
                    "filename": r_doc.original_filename,
                    "skills_count": len(skill_verdicts),
                    "skills": [],
                }

                print(f"--------------------------------------------------------------------------------")
                print(f"RESUME #{len(all_resumes_data) + 1}: {cand_name} ({r_doc.original_filename})")
                cand_skills = getattr(norm_r, "skills", []) or []
                print(f"Candidate Skills: {cand_skills[:12]}")
                print(f"--------------------------------------------------------------------------------")

                for v in skill_verdicts:
                    ev_texts = [ev_map[eid].text.replace("\n", " ").strip() for eid in v.evidence_ids if eid in ev_map]
                    ev_str = " | ".join(ev_texts) if ev_texts else "None"
                    if len(ev_str) > 120:
                        ev_str = ev_str[:117] + "..."

                    pts = v.coverage_score if v.coverage_score is not None else v.coverage

                    # Check logical correctness
                    # Is match logical based on evidence?
                    has_ev = len(v.evidence_ids) > 0
                    is_matched = v.status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}
                    logical_correct = (is_matched and has_ev) or (not is_matched and not has_ev)

                    cand_record["skills"].append({
                        "required_skill": v.requirement_text,
                        "candidate_evidence": ev_str,
                        "evidence_ids": v.evidence_ids,
                        "verdict": v.status.value,
                        "coverage_points": round(float(pts or 0.0), 2),
                        "method": v.method.value if v.method else "none",
                        "reasoning": v.reasoning,
                        "logical_correct": logical_correct,
                    })

                    print(f"  * Skill: {v.requirement_text}")
                    print(f"    - Evidence:  [{', '.join(v.evidence_ids)}] {ev_str}")
                    print(f"    - Verdict:   {v.status.value} (pts: {pts}) via {v.method}")
                    print(f"    - Logical:   {'YES' if logical_correct else 'NO'}")

                all_resumes_data.append(cand_record)
                if len(all_resumes_data) >= 8:
                    break
            if len(all_resumes_data) >= 8:
                break

    with open("real_resumes_skills_validation.json", "w", encoding="utf-8") as f:
        json.dump(all_resumes_data, f, indent=2, ensure_ascii=False)

    print(f"\n================================================================================")
    print(f"VALIDATION COMPLETED FOR {len(all_resumes_data)} REAL-WORLD RESUMES")
    print(f"================================================================================")
    return all_resumes_data


if __name__ == "__main__":
    asyncio.run(validate_real_resumes())
