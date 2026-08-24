from app.core.exceptions import ValidationException

VALID_DEPARTMENT_CODES = {
    "SOFTWARE_ENGINEERING",
    "DATA_ENGINEERING",
    "PMO",
    "QA",
    "SYSOPS",
    "ITOPS",
    "SECOPS",
    "SRE",
}

DEPARTMENT_ALIAS_MAP = {
    "SOFTWARE_ENGINEERING": "SOFTWARE_ENGINEERING",
    "ENGINEERING": "SOFTWARE_ENGINEERING",
    "ENG": "SOFTWARE_ENGINEERING",
    "DEVELOPMENT": "SOFTWARE_ENGINEERING",
    "SOFTWARE": "SOFTWARE_ENGINEERING",
    "DATA_ENGINEERING": "DATA_ENGINEERING",
    "DATA": "DATA_ENGINEERING",
    "DATA_SCIENCE": "DATA_ENGINEERING",
    "ANALYTICS": "DATA_ENGINEERING",
    "PMO": "PMO",
    "PROJECT_MANAGEMENT": "PMO",
    "PRODUCT_MANAGEMENT": "PMO",
    "QA": "QA",
    "QUALITY_ASSURANCE": "QA",
    "TESTING": "QA",
    "SOFTWARE_TESTING": "QA",
    "SYSOPS": "SYSOPS",
    "SYSTEM_OPERATIONS": "SYSOPS",
    "SYSADMIN": "SYSOPS",
    "ITOPS": "ITOPS",
    "IT_OPERATIONS": "ITOPS",
    "IT": "ITOPS",
    "SECOPS": "SECOPS",
    "SECURITY": "SECOPS",
    "CYBERSECURITY": "SECOPS",
    "SRE": "SRE",
    "SITE_RELIABILITY_ENGINEERING": "SRE",
    "DEVOPS": "SRE",
    "CLOUD": "SRE",
}


def get_experience_tier(duration_months: int | float | None) -> str:
    """Calculate canonical experience tier from normalized total experience in months.

    Rules:
      - < 24 months -> '0-1'
      - 24-71 months -> '2-5'
      - 72-131 months -> '6-10'
      - >= 132 months -> '11-15'
    """
    months = int(duration_months) if duration_months is not None else 0
    if months < 24:
        return "0-1"
    elif months <= 71:
        return "2-5"
    elif months <= 131:
        return "6-10"
    else:
        return "11-15"


def calibrate_experience(duration_months: int | float | None) -> tuple[str, str]:
    """Calibrate total experience in months to CD-Recruit category and level tier.

    Returns:
      (category, experience_tier) -> ('EXPERIENCED'/'FRESHER', '0-1'/'2-5'/'6-10'/'11-15')
    """
    tier = get_experience_tier(duration_months)
    category = "FRESHER" if tier == "0-1" else "EXPERIENCED"
    return category, tier


def map_department_code(department_input: str | None, default_code: str | None = "SOFTWARE_ENGINEERING") -> str:
    """Map arbitrary department text to a strict CD-Recruit department code.

    Raises ValidationException if unmapped and no valid default exists.
    """
    if department_input and department_input.strip():
        raw_clean = department_input.strip().upper().replace(" ", "_")
        if raw_clean in VALID_DEPARTMENT_CODES:
            return raw_clean
        if raw_clean in DEPARTMENT_ALIAS_MAP:
            return DEPARTMENT_ALIAS_MAP[raw_clean]

    if default_code and default_code.strip():
        default_clean = default_code.strip().upper().replace(" ", "_")
        if default_clean in VALID_DEPARTMENT_CODES:
            return default_clean

    raise ValidationException(
        f"Unable to map department '{department_input}' to any valid CD-Recruit department code "
        f"({', '.join(sorted(VALID_DEPARTMENT_CODES))})."
    )
