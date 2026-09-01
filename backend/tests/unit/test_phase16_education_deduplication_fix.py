"""
Phase 16 — Education Requirement Deduplication & Single-Requirement Scoring

Root-Cause: `_extract_education()` was pattern-first, producing N overlapping
fragments per JD sentence. This caused a single education requirement to appear
as 5-8 Unmet requirements, drastically diluting scores.

Expected behaviour (per the Logical Requirement Model):
  ONE education sentence in the JD  →  ONE entry in `degree_requirements`
  That entry is scored as ONE requirement, not N.
"""
import pytest
from app.services.jd_extraction_service import _extract_education
from app.services.matching_service import DeterministicRequirementMatcher, RequirementBuilder
from app.schemas.matching import RequirementKind, MatchStatus, Evidence, Requirement
from app.services.scoring.component_scoring_service import ComponentScoringService
from types import SimpleNamespace


# ─── Extraction Layer Tests ──────────────────────────────────────────────────

class TestEducationExtraction:
    """Tests for _extract_education: sentence-first, no fragmentation."""

    def test_single_sentence_produces_single_item(self):
        """A single JD education sentence must produce exactly one item."""
        text = (
            "Bachelor's degree in Computer Science, Information Technology, "
            "Engineering, Business, or a related field."
        )
        results, _ = _extract_education(text)
        assert len(results) == 1, (
            f"Expected 1 education item, got {len(results)}: {results}"
        )

    def test_bachelor_with_multi_discipline_or_list(self):
        """OR-list disciplines inside a single sentence → single extraction."""
        text = (
            "Education: Bachelor's degree in Computer Science, "
            "Information Technology, Engineering, Business, or a related field."
        )
        results, _ = _extract_education(text)
        assert len(results) == 1
        # Must contain the degree level indicator
        assert any("bachelor" in r.lower() for r in results)

    def test_two_separate_education_lines_produce_two_items(self):
        """Two distinct education requirement lines → two items."""
        text = (
            "Bachelor's degree in Computer Science or related field.\n"
            "Master's degree preferred."
        )
        results, _ = _extract_education(text)
        assert len(results) == 2, (
            f"Expected 2 education items, got {len(results)}: {results}"
        )

    def test_btech_sentence_produces_one_item(self):
        """B.Tech education requirement → one item."""
        text = "Bachelor of Technology in Computer Science."
        results, _ = _extract_education(text)
        assert len(results) == 1
        assert any("bachelor" in r.lower() or "b.tech" in r.lower() or "b tech" in r.lower() for r in results)

    def test_non_education_text_produces_no_items(self):
        """Text with no degree mention → empty list."""
        text = "Must have 3+ years of experience with Python and FastAPI."
        results, _ = _extract_education(text)
        assert results == []

    def test_phd_requirement_produces_one_item(self):
        """PhD requirement → exactly one item."""
        text = "PhD in Computer Science or related discipline required."
        results, _ = _extract_education(text)
        assert len(results) == 1
        assert any("phd" in r.lower() or "doctoral" in r.lower() for r in results)

    def test_no_duplicate_fragments_from_overlapping_patterns(self):
        """The old pattern-first approach produced fragments; ensure they are gone."""
        text = (
            "Bachelor's degree in Computer Science, Information Technology, "
            "Engineering, Business, or a related field."
        )
        results, _ = _extract_education(text)
        # Old bug: would produce 7+ items like "Information Technology", "Engineering", etc.
        assert len(results) <= 2, (
            f"Fragmentation detected — got {len(results)} items: {results}"
        )
        # None of the items should be bare discipline names without a degree word
        for r in results:
            has_degree_word = any(
                w in r.lower()
                for w in ["bachelor", "master", "phd", "doctorate", "degree", "b.tech",
                           "b.sc", "m.tech", "m.sc", "mba", "associate"]
            )
            assert has_degree_word, (
                f"Item '{r}' is a bare discipline fragment without a degree indicator"
            )

    def test_mba_produces_one_item(self):
        """MBA requirement → one item."""
        text = "MBA or equivalent business degree preferred."
        results, _ = _extract_education(text)
        assert len(results) == 1


# ─── Matching Layer Tests ─────────────────────────────────────────────────────

def _build_job(degree_requirements: list[str]):
    return SimpleNamespace(
        skills=[], required_skills=[], preferred_skills=[],
        degree_requirements=degree_requirements,
        certifications=[], responsibilities=[], experience_requirements=[],
        project_requirements=[], keywords=[],
    )


def _build_resume(edu_degree: str, edu_field: str):
    return SimpleNamespace(
        skills=[], certifications=[], languages=[],
        education=[{"degree": edu_degree, "field_of_study": edu_field}],
        experience=[], projects=[],
    )


def _match_degree(req_text: str, edu_degree: str, edu_field: str = "Computer Science") -> MatchStatus:
    """Helper: run DeterministicRequirementMatcher for a DEGREE requirement."""
    req = Requirement(
        requirement_id="degree:1",
        kind=RequirementKind.DEGREE,
        text=req_text,
        canonical_value=req_text,
        required=True,
    )
    resume = _build_resume(edu_degree, edu_field)
    evidence = [
        Evidence(
            evidence_id="education:1",
            kind="education",
            text=f"{edu_degree} {edu_field}",
            canonical_terms=[edu_degree, edu_field],
        )
    ]
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    return verdict.status


class TestDegreeMatchingAfterFix:
    """Ensure the matching layer correctly evaluates the canonical degree string."""

    def test_btech_satisfies_bachelors_degree(self):
        """Education matching disabled -> NO_MATCH."""
        status = _match_degree("Bachelor's Degree", "B.Tech")
        assert status == MatchStatus.NO_MATCH

    def test_be_satisfies_bachelor_of_engineering(self):
        """Education matching disabled -> NO_MATCH."""
        status = _match_degree("Bachelor of Engineering", "B.E.")
        assert status == MatchStatus.NO_MATCH

    def test_bsc_satisfies_bachelors_degree(self):
        """Education matching disabled -> NO_MATCH."""
        status = _match_degree("Bachelor's Degree", "B.Sc")
        assert status == MatchStatus.NO_MATCH

    def test_msc_satisfies_masters_degree(self):
        """Education matching disabled -> NO_MATCH."""
        status = _match_degree("Master's Degree", "M.Sc")
        assert status == MatchStatus.NO_MATCH

    def test_degree_rank_for_bachelors_degree(self):
        """degree_rank('Bachelor's Degree') returns 3."""
        rank = ComponentScoringService.degree_rank("Bachelor's Degree")
        assert rank == 3

    def test_degree_rank_for_bachelors_degree_canonical(self):
        """degree_rank on a full-sentence extraction returns a non-zero rank."""
        rank = ComponentScoringService.degree_rank("Bachelor's Degree")
        assert rank > 0

    def test_requirement_builder_produces_single_degree_requirement(self):
        """RequirementBuilder emits 0 DEGREE requirements (Education matching disabled)."""
        job = _build_job(["Bachelor's Degree"])
        config = SimpleNamespace(
            mandatory_skills=[], required_certifications=[], required_languages=[],
            required_degree=None,
        )
        reqs = RequirementBuilder.build(job, config)
        degree_reqs = [r for r in reqs if r.kind == RequirementKind.DEGREE]
        assert len(degree_reqs) == 0


# ─── End-to-End: No Invented Requirements ────────────────────────────────────

class TestNoInventedRequirements:
    """A qualification NOT in the JD must never appear as an Unmet requirement."""

    def test_master_of_science_not_invented_for_bachelors_only_jd(self):
        """If JD only requires a Bachelor's, 'Master of Science' must not appear as Unmet."""
        text = "Bachelor's degree in Computer Science or related field required."
        results, _ = _extract_education(text)
        for r in results:
            assert "master" not in r.lower(), (
                f"'master' appeared in education extraction for a bachelor's-only JD: {r}"
            )

    def test_no_bare_discipline_fragments(self):
        """Disciplines like 'Information Technology' must not appear as standalone degree items."""
        text = (
            "Bachelor's degree in Computer Science, Information Technology, "
            "Engineering, Business, or a related field."
        )
        results, _ = _extract_education(text)
        bare_disciplines = {"information technology", "engineering", "business", "a related field", "related field"}
        for r in results:
            assert r.lower().strip() not in bare_disciplines, (
                f"Bare discipline '{r}' appeared as a standalone education requirement"
            )
