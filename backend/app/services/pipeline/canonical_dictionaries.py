RULESET_VERSION = "1.0.0"

SKILL_ALIASES = {
    "py": "Python", "python": "Python", "python3": "Python",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "fastapi": "FastAPI", "sqlalchemy": "SQLAlchemy", "sql": "SQL",
    "nodejs": "Node.js", "node.js": "Node.js", "reactjs": "React", "react": "React",
    "js": "JavaScript", "javascript": "JavaScript", "ts": "TypeScript", "typescript": "TypeScript",
    "docker": "Docker", "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "aws": "AWS", "azure": "Azure", "java": "Java", "c++": "C++",
}
DEGREE_ALIASES = {
    "b.e.": "Bachelor of Engineering", "be": "Bachelor of Engineering",
    "bachelor of engg": "Bachelor of Engineering", "bachelor of engineering": "Bachelor of Engineering",
    "b.tech": "Bachelor of Technology", "btech": "Bachelor of Technology",
    "m.e.": "Master of Engineering", "me": "Master of Engineering",
    "m.tech": "Master of Technology", "mtech": "Master of Technology",
    "b.sc": "Bachelor of Science", "bsc": "Bachelor of Science", "bachelor of science": "Bachelor of Science",
    "m.sc": "Master of Science", "msc": "Master of Science", "master of science": "Master of Science",
    "mba": "Master of Business Administration", "phd": "Doctor of Philosophy",
}
TITLE_ALIASES = {
    "c++ developer": "Software Engineer", "software developer": "Software Engineer",
    "sr. backend dev": "Senior Backend Engineer", "sr backend dev": "Senior Backend Engineer",
    "backend developer": "Backend Engineer", "python developer": "Software Engineer",
    "full stack developer": "Full Stack Engineer", "frontend developer": "Frontend Engineer",
}
LANGUAGE_ALIASES = {
    "eng": "English", "english": "English", "hin": "Hindi", "hindi": "Hindi",
    "spa": "Spanish", "spanish": "Spanish", "fre": "French", "french": "French",
    "deu": "German", "german": "German", "tam": "Tamil", "tamil": "Tamil",
    "tel": "Telugu", "telugu": "Telugu", "kan": "Kannada", "kannada": "Kannada",
}
CERTIFICATION_ALIASES = {
    "aws solutions architect": "AWS Certified Solutions Architect",
    "aws certified solutions architect": "AWS Certified Solutions Architect",
    "pmp": "Project Management Professional (PMP)",
    "project management professional": "Project Management Professional (PMP)",
}
DOMAIN_ALIASES = {
    "it": "Software Engineering", "information technology": "Software Engineering",
    "software development": "Software Engineering", "software engineering": "Software Engineering",
    "devops": "DevOps", "data science": "Data Science", "product management": "Product Management",
}
LOCATION_ALIASES = {
    "bangalore": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "bengaluru": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "bengaluru, india": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "san francisco, ca": {"city": "San Francisco", "region": "California", "country": "United States", "country_code": "US", "display_name": "San Francisco, California, United States"},
    "new york, ny": {"city": "New York", "region": "New York", "country": "United States", "country_code": "US", "display_name": "New York, New York, United States"},
}
