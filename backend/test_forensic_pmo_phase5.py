import json
from types import SimpleNamespace
from app.services.matching_service import RequirementBuilder, EvidenceBuilder, DeterministicRequirementMatcher
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from app.schemas.matching import MatchStatus, MatchMethod

PMO_JD = SimpleNamespace(
    job_title="PMO Analyst / Project Coordinator",
    required_skills=[
        "Project Management", "Jira", "Confluence", "Excel", "Power BI",
        "Status Reporting", "Risk Management", "Stakeholder Management", "Milestone Tracking"
    ],
    preferred_skills=["Power BI", "RAID Logs", "PowerPoint", "MS Project"],
    skills=[
        "Project Management", "Jira", "Confluence", "Excel", "Power BI",
        "Status Reporting", "Risk Management", "Stakeholder Management", "Milestone Tracking", "RAID Logs"
    ],
    responsibilities=[
        "Maintain project schedules, milestone trackers, and RAID logs.",
        "Prepare weekly and monthly management status reports and dashboards.",
        "Coordinate stakeholder meetings, action items, and cross-functional team deliverables.",
        "Track tasks and project documentation using Jira and Confluence.",
        "Monitor project deliverables against timelines and perform bottleneck analysis."
    ],
    experience_requirements=[{"minimum_months": 0, "maximum_months": 36, "display_value": "0-3 years"}],
    degree_requirements=["Bachelor's degree in Computer Science, Information Technology, or Business Administration."],
    project_requirements=[],
    certifications=[],
    keywords=["Project Management", "PMO", "Jira", "Confluence", "Excel", "Power BI", "Status Reporting"],
)

RAHUL_MENON_RESUME = SimpleNamespace(
    candidate_name="Rahul Menon",
    skills=[
        "Project Management", "Jira", "Confluence", "Excel", "Power BI",
        "RAID Logs", "Milestone Tracking", "Status Reporting", "Risk Management", "Stakeholder Management"
    ],
    education=[{"degree": "Bachelor of Engineering — Computer Science", "institution": "Anna University"}],
    certifications=[],
    languages=["English"],
    experience=[
        {
            "company": "Apex Global Solutions",
            "title": "PMO Analyst",
            "employment_type": "Full-time",
            "duration_months": 36,
            "description": "Coordinated project activities across engineering and IT teams. Maintained project schedules and milestone trackers. Prepared weekly and monthly project status reports and management dashboards using Excel and Power BI. Maintained RAID logs, monitored project deliverables against timelines, and managed documentation using Confluence and Jira.",
            "technologies": ["Jira", "Confluence", "Excel", "Power BI", "RAID Logs"],
            "responsibilities": [
                "Coordinated project activities across engineering and IT teams",
                "Maintained project schedules and milestone trackers",
                "Prepared weekly/monthly project status reports and dashboards using Excel and Power BI",
                "Maintained RAID logs and monitored project deliverables against timelines",
                "Managed project documentation using Confluence and tracked tasks using Jira"
            ]
        }
    ],
    projects=[
        {
            "name": "PMO Governance & Milestone Dashboard",
            "description": "Developed Power BI & Excel management dashboard for tracking project milestones, dependencies, RAID logs, risks, and action items.",
            "technologies": ["Power BI", "Excel", "Jira", "Confluence"],
            "deliverables": ["Milestone Tracker", "RAID Log", "Executive Status Report"]
        }
    ]
)

AARAV_SHARMA_RESUME = SimpleNamespace(
    candidate_name="Aarav Sharma",
    skills=[
        "Excel", "PowerPoint", "Jira", "Confluence", "Power BI",
        "Project Tracking", "Status Reporting", "Meeting Minutes", "Action Tracking", "Risk/Issue Logs", "Documentation"
    ],
    education=[{"degree": "Bachelor of Technology — Information Technology", "institution": "VTU"}],
    certifications=[],
    languages=["English"],
    experience=[
        {
            "company": "TechStart Inc",
            "title": "Project Coordination Intern",
            "employment_type": "Internship",
            "duration_months": 12,
            "description": "Supported project tracking, status reporting, meeting minutes, action tracking, and risk/issue logs. Prepared weekly status reports, stakeholder progress summaries, schedule deviation and bottleneck analysis, meeting notes, PowerPoint presentations, Excel reports, and progress updates using Jira and Confluence.",
            "technologies": ["Excel", "PowerPoint", "Jira", "Confluence", "Power BI"],
            "responsibilities": [
                "Tracked task status, owners, deadlines, risks, and KPIs",
                "Prepared weekly status reports and stakeholder progress summaries",
                "Conducted action-item tracking, schedule deviation, and bottleneck analysis",
                "Maintained internship meeting notes, action items, PowerPoint presentations, and Excel reports"
            ]
        }
    ],
    projects=[
        {
            "name": "Academic Project Tracking Dashboard",
            "description": "Built academic dashboard tracking milestones, task status, owners, deadlines, risks, and KPIs using Excel, Power BI, Jira, and Confluence.",
            "technologies": ["Excel", "Power BI", "Jira", "Confluence"],
            "deliverables": ["Academic Dashboard", "Action Item Log"]
        }
    ]
)

DEFAULT_CONFIG = SimpleNamespace(
    mandatory_skills=[],
    min_experience_years=0,
    required_degree="Bachelor's degree",
    required_certifications=[],
    required_languages=[],
)

def evaluate_pmo_candidate(candidate_name: str, resume: SimpleNamespace):
    matcher = DeterministicRequirementMatcher()
    requirements = RequirementBuilder.build(PMO_JD, DEFAULT_CONFIG)
    extracted = SimpleNamespace(
        candidate_name=resume.candidate_name,
        skills=resume.skills,
        education=resume.education,
        certifications=resume.certifications,
        languages=resume.languages,
        experience=resume.experience,
        projects=resume.projects,
    )
    evidence = EvidenceBuilder.build(extracted)
    verdicts = [matcher.match(req, resume, evidence) for req in requirements]
    scoring_svc = ComponentScoringService()
    components = scoring_svc.score(resume, PMO_JD, DEFAULT_CONFIG, projects=extracted.projects, match_verdicts=verdicts)
    applicable = WeightCalculationService.applicable_categories(PMO_JD, DEFAULT_CONFIG)
    weighted_schema, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(components, DEFAULT_CONFIG, applicable_categories=applicable)
    final_score = WeightCalculationService.final_score(weighted_total, 0, 0, components, applicable)

    print(f"\n================ EVALUATION: {candidate_name} ================")
    print(f"Overall Score: {final_score:.2f}%")
    print(f"Required Skills: {components.skills.score:.2f}%")
    print(f"Responsibilities: {components.responsibilities.score:.2f}%")
    print(f"Projects: {components.projects.score:.2f}%")
    print(f"Preferred Skills: {components.preferred_skills.score:.2f}%")
    print(f"Experience: {components.experience.score:.2f}%")
    print(f"Education: {components.education.score:.2f}%")
    print("\nResponsibility Verdicts:")
    for v in verdicts:
        if str(v.requirement_id).startswith("responsibility:"):
            print(f"  [{v.requirement_id}] status={v.status.value} concepts_matched={getattr(v, 'matched_concepts', [])} missing={getattr(v, 'missing_concepts', [])} reasoning={v.reasoning}")
    print("\nEducation Component Details:")
    print(f"  Score: {components.education.score:.2f}% explanation={components.education.explanation}")
    print("\nExperience Component Details:")
    print(f"  Score: {components.experience.score:.2f}% explanation={components.experience.explanation}")

if __name__ == "__main__":
    evaluate_pmo_candidate("Rahul Menon", RAHUL_MENON_RESUME)
    evaluate_pmo_candidate("Aarav Sharma", AARAV_SHARMA_RESUME)
