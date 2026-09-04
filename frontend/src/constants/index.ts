import { NavStage, AIPipelineStage, PipelineStage } from '@/types'

// ─── Sidebar Navigation Stages (5 items) ──────────────────
export const NAV_STAGES: NavStage[] = [
  {
    id: 'document-upload',
    label: 'Document Upload',
    step: 1,
    icon: 'Upload',
    description: 'Upload job description document',
    route: '/',
  },
  {
    id: 'weightage-setting',
    label: 'Weightage Setting',
    step: 2,
    icon: 'Scale',
    description: 'Configure scoring criteria and weights',
    route: '/weightage',
  },
  {
    id: 'resume-upload',
    label: 'Resume Upload',
    step: 3,
    icon: 'FolderUp',
    description: 'Upload candidate resume files',
    route: '/resume-upload',
  },
  {
    id: 'candidate-ranking',
    label: 'Candidate Ranking',
    step: 4,
    icon: 'ListOrdered',
    description: 'Run AI pipeline and view ranked candidates',
    route: '/ranking',
  },
  {
    id: 'recruiter-dashboard',
    label: 'Recruiter Dashboard',
    step: 5,
    icon: 'LayoutDashboard',
    description: 'Review and action screened candidates',
    route: '/dashboard',
  },
]

// ─── AI Processing Pipeline (7 visual stages) ────────────────
export const AI_PIPELINE_STAGES: AIPipelineStage[] = [
  {
    id: 'document-ingestion',
    label: 'Document Ingestion',
    shortLabel: 'Ingestion',
    icon: 'FolderInput',
    description: 'Parse and ingest JD and resume files',
  },
  {
    id: 'weightage-setup',
    label: 'Weightage Setup',
    shortLabel: 'Weightage',
    icon: 'Scale',
    description: 'Apply configured scoring weights',
  },
  {
    id: 'ai-information-extraction',
    label: 'AI Information Extraction',
    shortLabel: 'Extraction',
    icon: 'ScanText',
    description: 'Extract candidate skills, experience, education',
  },
  {
    id: 'data-normalization',
    label: 'Data Normalization',
    shortLabel: 'Normalization',
    icon: 'GitMerge',
    description: 'Normalize and standardize extracted fields',
  },
  {
    id: 'matching-engine',
    label: 'Matching Engine',
    shortLabel: 'Matching',
    icon: 'Cpu',
    description: 'Semantic matching of candidates to JD',
  },
  {
    id: 'candidate-ranking',
    label: 'Candidate Ranking',
    shortLabel: 'Ranking',
    icon: 'ListOrdered',
    description: 'Rank candidates by weighted composite score',
  },
  {
    id: 'ai-explanation',
    label: 'AI Explanation',
    shortLabel: 'Explanation',
    icon: 'Sparkles',
    description: 'Generate AI rationale per candidate',
  },
]

// ─── Legacy PIPELINE_STAGES (used by store for step count) ────
export const PIPELINE_STAGES: PipelineStage[] = NAV_STAGES.map((s) => ({
  id: s.id,
  label: s.label,
  shortLabel: s.label,
  step: s.step,
  icon: s.icon,
  description: s.description,
}))

export const TOTAL_STEPS = NAV_STAGES.length

export const DEFAULT_WEIGHTS = [
  {
    id: 'required_skills' as const,
    label: 'Required Skills',
    description: 'Mandatory technical skills and qualifications',
    weight: 45,
    locked: false,
    color: '#f43f5e',
    badgeBg: '#ffe4e6',
    badgeText: '#be123c',
    iconBg: '#ffe4e6',
    iconColor: '#e11d48',
    icon: 'Code2',
  },
  {
    id: 'responsibilities' as const,
    label: 'Responsibilities',
    description: 'Demonstrated experience, deliverables, and role execution',
    weight: 40,
    locked: false,
    color: '#10b981',
    badgeBg: '#dcfce7',
    badgeText: '#15803d',
    iconBg: '#dcfce7',
    iconColor: '#16a34a',
    icon: 'Briefcase',
  },
  {
    id: 'preferred_skills' as const,
    label: 'Preferred Skills',
    description: 'Nice-to-have bonus technologies and competencies',
    weight: 15,
    locked: false,
    color: '#3b82f6',
    badgeBg: '#dbeafe',
    badgeText: '#1d4ed8',
    iconBg: '#dbeafe',
    iconColor: '#2563eb',
    icon: 'Award',
  },
]

export const ROLE_PRESETS = [
  {
    id: 'standard',
    label: 'Standard (45 / 40 / 15)',
    weights: {
      required_skills: 45,
      responsibilities: 40,
      preferred_skills: 15,
    },
  },
  {
    id: 'skills-heavy',
    label: 'Skills Heavy (55 / 35 / 10)',
    weights: {
      required_skills: 55,
      responsibilities: 35,
      preferred_skills: 10,
    },
  },
  {
    id: 'execution-heavy',
    label: 'Execution Heavy (40 / 50 / 10)',
    weights: {
      required_skills: 40,
      responsibilities: 50,
      preferred_skills: 10,
    },
  },
]
