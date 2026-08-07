RULESET_VERSION = "1.0.0"

SKILL_ALIASES = {
    "py": "Python", "python": "Python", "python3": "Python",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "fastapi": "FastAPI", "sqlalchemy": "SQLAlchemy", "sql": "SQL",
    "nodejs": "Node.js", "node.js": "Node.js", "reactjs": "React", "react": "React",
    "js": "JavaScript", "javascript": "JavaScript", "ts": "TypeScript", "typescript": "TypeScript",
    "docker": "Docker", "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "aws": "AWS", "aws cloud": "AWS", "azure": "Azure", "gcp": "GCP", "google cloud": "GCP",
    "java": "Java", "c++": "C++", "c#": "C#", "net": ".NET", ".net": ".NET",
    "html": "HTML", "html5": "HTML", "css": "CSS", "css3": "CSS",
    "mongodb": "MongoDB", "mongo": "MongoDB", "jenkins": "Jenkins",
    "terraform": "Terraform", "dynamodb": "DynamoDB", "redis": "Redis",
    "lambda": "AWS Lambda", "aws lambda": "AWS Lambda",
    "api gateway": "AWS API Gateway", "aws api gateway": "AWS API Gateway",
    "s3": "AWS S3", "aws s3": "AWS S3", "ec2": "AWS EC2", "aws ec2": "AWS EC2",
    "graphql": "GraphQL", "rest": "REST API", "rest api": "REST API", "restful": "REST API",
    "linux": "Linux", "unix": "Linux", "gitlab": "GitLab", "ci/cd": "CI/CD", "cicd": "CI/CD",
    "golang": "Go", "go": "Go", "spring": "Spring Boot", "spring boot": "Spring Boot",
    "express": "Express", "express.js": "Express", "vue": "Vue", "vue.js": "Vue",
    "angular": "Angular", "angularjs": "Angular", "nextjs": "Next.js", "next.js": "Next.js",
    "tailwind": "Tailwind", "tailwindcss": "Tailwind", "kafka": "Kafka",
    "elasticsearch": "Elasticsearch", "elastic": "Elasticsearch", "rabbitmq": "RabbitMQ",
    "rust": "Rust", "redux": "Redux", "pandas": "Pandas", "numpy": "NumPy",
    "scikit-learn": "Scikit-learn", "sklearn": "Scikit-learn",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "pytest": "Pytest",
    "bash": "Bash", "shell": "Shell", "mysql": "MySQL", "sqlite": "SQLite", "oracle": "Oracle",
}

DEGREE_ALIASES = {
    "b.e.": "Bachelor of Engineering", "be": "Bachelor of Engineering",
    "bachelor of engg": "Bachelor of Engineering", "bachelor of engineering": "Bachelor of Engineering",
    "b.tech": "Bachelor of Technology", "btech": "Bachelor of Technology", "b.technology": "Bachelor of Technology", "bachelor of technology": "Bachelor of Technology",
    "m.e.": "Master of Engineering", "me": "Master of Engineering",
    "m.tech": "Master of Technology", "mtech": "Master of Technology",
    "b.sc": "Bachelor of Science", "bsc": "Bachelor of Science", "bachelor of science": "Bachelor of Science", "b.s.": "Bachelor of Science", "bs": "Bachelor of Science",
    "m.sc": "Master of Science", "msc": "Master of Science", "master of science": "Master of Science", "m.s.": "Master of Science", "ms": "Master of Science",
    "bca": "Bachelor of Computer Applications", "mca": "Master of Computer Applications",
    "b.a.": "Bachelor of Arts", "ba": "Bachelor of Arts", "bachelor of arts": "Bachelor of Arts",
    "b.com": "Bachelor of Commerce", "bcom": "Bachelor of Commerce",
    "mba": "Master of Business Administration", "phd": "Doctor of Philosophy", "ph.d": "Doctor of Philosophy",
}

TITLE_ALIASES = {
    "c++ developer": "Software Engineer", "software developer": "Software Engineer",
    "sr. backend dev": "Senior Backend Engineer", "sr backend dev": "Senior Backend Engineer",
    "backend developer": "Backend Engineer", "python developer": "Python Developer",
    "full stack developer": "Full Stack Engineer", "frontend developer": "Frontend Engineer",
    "sde": "Software Engineer", "sde-1": "Software Engineer", "sde-2": "Software Engineer",
    "sde 1": "Software Engineer", "sde 2": "Software Engineer", "sde 3": "Senior Software Engineer",
    "senior software engineer": "Senior Software Engineer", "lead engineer": "Lead Engineer",
    "tech lead": "Tech Lead", "technical lead": "Tech Lead", "intern": "Software Engineer Intern",
    "database management intern": "Database Management Intern", "database intern": "Database Management Intern",
    "software engineer intern": "Software Engineer Intern", "devops engineer": "DevOps Engineer",
    "data engineer": "Data Engineer", "data scientist": "Data Scientist",
}

LANGUAGE_ALIASES = {
    "eng": "English", "english": "English", "hin": "Hindi", "hindi": "Hindi",
    "spa": "Spanish", "spanish": "Spanish", "fre": "French", "french": "French",
    "deu": "German", "german": "German", "tam": "Tamil", "tamil": "Tamil",
    "tel": "Telugu", "telugu": "Telugu", "kan": "Kannada", "kannada": "Kannada",
    "mal": "Malayalam", "malayalam": "Malayalam", "mar": "Marathi", "marathi": "Marathi",
}

CERTIFICATION_ALIASES = {
    "aws solutions architect": "AWS Certified Solutions Architect",
    "aws certified solutions architect": "AWS Certified Solutions Architect",
    "pmp": "Project Management Professional (PMP)",
    "project management professional": "Project Management Professional (PMP)",
    "certified kubernetes administrator": "Certified Kubernetes Administrator (CKA)",
    "cka": "Certified Kubernetes Administrator (CKA)",
}

DOMAIN_ALIASES = {
    "it": "Software Engineering", "information technology": "Software Engineering",
    "software development": "Software Engineering", "software engineering": "Software Engineering",
    "devops": "DevOps", "data science": "Data Science", "product management": "Product Management",
}

LOCATION_ALIASES = {
    "coimbatore": {"city": "Coimbatore", "region": "Tamil Nadu", "country": "India", "country_code": "IN", "display_name": "Coimbatore, Tamil Nadu, India"},
    "chennai": {"city": "Chennai", "region": "Tamil Nadu", "country": "India", "country_code": "IN", "display_name": "Chennai, Tamil Nadu, India"},
    "bangalore": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "bengaluru": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "bengaluru, india": {"city": "Bengaluru", "region": "Karnataka", "country": "India", "country_code": "IN", "display_name": "Bengaluru, Karnataka, India"},
    "mumbai": {"city": "Mumbai", "region": "Maharashtra", "country": "India", "country_code": "IN", "display_name": "Mumbai, Maharashtra, India"},
    "delhi": {"city": "Delhi", "region": "Delhi", "country": "India", "country_code": "IN", "display_name": "Delhi, India"},
    "hyderabad": {"city": "Hyderabad", "region": "Telangana", "country": "India", "country_code": "IN", "display_name": "Hyderabad, Telangana, India"},
    "pune": {"city": "Pune", "region": "Maharashtra", "country": "India", "country_code": "IN", "display_name": "Pune, Maharashtra, India"},
    "kolkata": {"city": "Kolkata", "region": "West Bengal", "country": "India", "country_code": "IN", "display_name": "Kolkata, West Bengal, India"},
    "noida": {"city": "Noida", "region": "Uttar Pradesh", "country": "India", "country_code": "IN", "display_name": "Noida, Uttar Pradesh, India"},
    "gurgaon": {"city": "Gurugram", "region": "Haryana", "country": "India", "country_code": "IN", "display_name": "Gurugram, Haryana, India"},
    "gurugram": {"city": "Gurugram", "region": "Haryana", "country": "India", "country_code": "IN", "display_name": "Gurugram, Haryana, India"},
    "san francisco, ca": {"city": "San Francisco", "region": "California", "country": "United States", "country_code": "US", "display_name": "San Francisco, California, United States"},
    "san francisco": {"city": "San Francisco", "region": "California", "country": "United States", "country_code": "US", "display_name": "San Francisco, California, United States"},
    "new york, ny": {"city": "New York", "region": "New York", "country": "United States", "country_code": "US", "display_name": "New York, New York, United States"},
    "new york": {"city": "New York", "region": "New York", "country": "United States", "country_code": "US", "display_name": "New York, New York, United States"},
    "london": {"city": "London", "region": "London", "country": "United Kingdom", "country_code": "GB", "display_name": "London, United Kingdom"},
    "london, uk": {"city": "London", "region": "London", "country": "United Kingdom", "country_code": "GB", "display_name": "London, United Kingdom"},
}
