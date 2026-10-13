import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from app.services.jd_extraction_service import JDExtractionService
from app.services.matching_service import RequirementBuilder, RequirementKind


POLLUTED_JD_TEXT = """Job Title: Associate Software Engineer
Job Code: CD_83_JOB
Required Skills: NodeJS, ReactJS

Description:
<span id="spandesc"><ul style="color:rgb(0, 0, 0); font-style:normal; font-weight:400; letter-spacing:normal; text-indent:0px; text-transform:none; white-space:normal; word-spacing:0px; text-decoration:none"><li><p style="margin-top:0px"><span>Develop and maintain web applications using React.js, Node.js, Express.js, and MongoDB.</span><br/></p></li><li><p style="margin-top:0px"><span>Build reusable React components and front-end libraries for future use.</span><br/></p></li><li><p style="margin-top:0px"><span>Optimize components for maximum performance across a variety of web-capable devices and browsers.</span><br/></p></li><li><p style="margin-top:0px"><span>Collaborate with designers to translate UI/UX wireframes into high-quality code.</span><br/></p></li><li><p style="margin-top:0px"><span>Implement state management solutions like Redux, Context API, or similar.</span><br/></p></li><li><p style="margin-top:0px"><span>Integrate RESTful APIs and third-party services into applications.</span><br/></p></li><li><p style="margin-top:0px"><span>Write clean, scalable, and maintainable code following best practices.</span><br/></p></li><li><p style="margin-top:0px"><span>Conduct thorough testing and debugging to ensure application reliability.</span><br/></p></li><li><p style="margin-top:0px"><span>Work in an Agile development environment, participating in daily stand-ups and sprint planning.</span><br/></p></li><li><p style="margin-top:0px"><span>Stay up to date with the latest front-end development trends and technologies.</span><br/></p></li></ul><div><br/></div></span><br/>"""

CLEAN_JD_TEXT = """Job Title: Associate Software Engineer
Job Code: CD_83_JOB
Required Skills: Node.js, React, MongoDB, Express

Description:
Develop and maintain web applications using React.js, Node.js, Express.js, and MongoDB.
Build reusable React components and front-end libraries for future use.
Write clean, scalable, and maintainable code following best practices.

Education:
Bachelor's degree in Computer Science or related field.
"""


@pytest.mark.asyncio
async def test_extraction_rejects_css_properties_and_best_practices_as_degree() -> None:
    service = JDExtractionService(
        document_repository=MagicMock(),
        parsed_repository=MagicMock(),
        extracted_repository=MagicMock(),
    )
    doc_id = uuid4()
    extracted = await service.extract_from_raw_text(POLLUTED_JD_TEXT, doc_id)

    # 1. CSS properties must NOT be extracted as skills or required skills
    disallowed_css = {
        "font-style:normal",
        "font-weight:400",
        "letter-spacing:normal",
        "text-indent:0px",
        "text-transform:none",
        "white-space:normal",
        "word-spacing:0px",
        "text-decoration:none",
        "color:rgb(0, 0, 0)",
    }
    all_extracted_skills = set(s.casefold() for s in extracted.skills)
    all_extracted_req_skills = set(s.casefold() for s in extracted.required_skills)

    for css_prop in disallowed_css:
        assert css_prop.casefold() not in all_extracted_skills, f"CSS property '{css_prop}' found in extracted.skills"
        assert css_prop.casefold() not in all_extracted_req_skills, f"CSS property '{css_prop}' found in extracted.required_skills"

    # 2. "best practices" must NOT be extracted as a degree requirement
    all_extracted_edu = [e.casefold() for e in extracted.education]
    assert not any("best practices" in e for e in all_extracted_edu), f"'best practices' incorrectly extracted in education: {extracted.education}"

    # 3. Legitimate skills from required skills or responsibilities must be present
    assert any("node" in s for s in all_extracted_skills)
    assert any("react" in s for s in all_extracted_skills)


@pytest.mark.asyncio
async def test_extraction_clean_jd() -> None:
    service = JDExtractionService(
        document_repository=MagicMock(),
        parsed_repository=MagicMock(),
        extracted_repository=MagicMock(),
    )
    doc_id = uuid4()
    extracted = await service.extract_from_raw_text(CLEAN_JD_TEXT, doc_id)

    all_extracted_skills = set(s.casefold() for s in extracted.skills)
    assert any("node" in s for s in all_extracted_skills)
    assert any("react" in s for s in all_extracted_skills)
    assert any("mongo" in s for s in all_extracted_skills)

    all_extracted_edu = [e.casefold() for e in extracted.education]
    assert any("bachelor" in e for e in all_extracted_edu)
    assert not any("best practices" in e for e in all_extracted_edu)


def test_requirement_builder_filters_legacy_css_and_non_degree() -> None:
    job = MagicMock()
    job.skills = ["Node.js", "font-style:normal", "font-weight:400", "React.js"]
    job.required_skills = ["Node.js", "font-style:normal", "letter-spacing:normal", "text-indent:0px", "white-space:normal"]
    job.preferred_skills = []
    job.degree_requirements = ["best practices", "Bachelor's Degree"]
    job.experience_requirements = []
    job.certifications = []
    job.responsibilities = []
    job.project_requirements = []
    job.requirement_classifications = {}
    job.raw_metadata = {}

    config = MagicMock()
    config.mandatory_skills = []
    config.required_certifications = []
    config.required_languages = []

    requirements = RequirementBuilder.build(job, config)

    skill_texts = [r.text for r in requirements if r.kind == RequirementKind.SKILL]
    assert "Node.js" in skill_texts
    assert "font-style:normal" not in skill_texts
    assert "font-weight:400" not in skill_texts
    assert "letter-spacing:normal" not in skill_texts
    assert "text-indent:0px" not in skill_texts
    assert "white-space:normal" not in skill_texts

    degree_texts = [r.text for r in requirements if r.kind == RequirementKind.DEGREE]
    assert "Bachelor's Degree" in degree_texts
    assert "best practices" not in degree_texts
