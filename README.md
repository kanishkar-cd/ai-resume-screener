# Enterprise AI Resume Screener (`ai-resume-screener`)

## Project Overview
An enterprise-grade, scalable AI-powered Resume Screener built with a monorepo architecture. Designed for high availability, security, and modularity across multiple development stages (Stage 1 to Stage 8).

## Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.12)
- **ORM & Database**: SQLAlchemy 2.0, Alembic, PostgreSQL
- **Data Validation**: Pydantic v2

### Frontend
- **Framework**: React (TypeScript, Vite)
- **UI Component Library**: Material UI (MUI)

### Infrastructure & DevOps
- **Containerization**: Docker & Docker Compose
- **CI/CD**: GitHub Actions (Workflow Placeholders)

---

## Repository Branching Strategy

```text
main
 └── develop
      └── feature/*
```

- **`main`**: Production-ready code. Protected branch.
- **`develop`**: Integration branch for pre-production testing.
- **`feature/*`**: Isolated feature development branches.

---

## Project Structure & Purpose

```text
ai-resume-screener/
├── .github/              # GitHub configurations, issue templates, and CI/CD workflows
│   └── workflows/        # CI/CD pipeline automation definitions
├── backend/              # Core Python backend service (FastAPI, SQLAlchemy, Pydantic)
│   ├── app/              # Backend application code (modules, services, models - to be built)
│   ├── tests/            # Automated test suite (unit, integration, e2e)
│   ├── .env.example      # Environment variable template for backend
│   ├── alembic.ini       # Alembic database migration configuration
│   ├── main.py           # Application entry point placeholder
│   └── requirements.txt  # Python dependency list placeholder
├── database/             # Database management assets
│   ├── migrations/       # Schema migration scripts managed by Alembic
│   └── seed/             # Database initial seed scripts and sample data
├── docker/               # Docker configurations, container scripts, and compose overrides
├── docs/                 # Project documentation and architectural specifications
│   ├── api/              # OpenAPI specs and API documentation
│   ├── architecture/     # System design diagrams and architectural decision records (ADRs)
│   ├── database/         # ER diagrams and schema documentation
│   └── meeting-notes/    # Architectural alignment and sprint meeting records
├── frontend/             # Single-page frontend application (React, TypeScript, Vite, MUI)
│   ├── public/           # Static web assets
│   └── src/              # React source code (components, views, state management)
├── scripts/              # Development setup, maintenance, and utility scripts
├── .env.example          # Environment variable template for container orchestration
├── .gitignore            # Git exclusion rules
├── docker-compose.yml    # Docker Compose multi-container orchestration definition placeholder
├── LICENSE               # MIT License
└── README.md             # Project overview and developer architecture documentation
```

---

## Stage Scalability Roadmap (Stages 1–8)

The directory architecture is structured to support seamless stage expansion without requiring structural refactoring:
- **Stage 1**: Foundation & Authentication Setup
- **Stage 2**: Database Schema & Migration Architecture
- **Stage 3**: Resume Ingestion & Parsing Engine
- **Stage 4**: AI/LLM Scoring & Matching Service
- **Stage 5**: HR Dashboard & Candidate Review UI
- **Stage 6**: Analytics & Enterprise Reporting
- **Stage 7**: CI/CD Pipelines & Automated Testing
- **Stage 8**: Production Hardening & Cloud Deployment
