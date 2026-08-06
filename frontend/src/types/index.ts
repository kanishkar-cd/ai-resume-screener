// ─── Navigation Stage (Sidebar) ──────────────────────────────
export type NavStageId =
  | 'document-upload'
  | 'weightage-setting'
  | 'resume-upload'
  | 'candidate-ranking'
  | 'recruiter-dashboard'

export interface NavStage {
  id: NavStageId
  label: string
  step: number
  icon: string
  description: string
  route: string
}

// ─── AI Processing Pipeline Stage (Visual Rail) ───────────────
export type AIPipelineStageId =
  | 'document-ingestion'
  | 'weightage-setup'
  | 'ai-information-extraction'
  | 'data-normalization'
  | 'matching-engine'
  | 'candidate-ranking'
  | 'ai-explanation'

export type AIPipelineStageStatus = 'pending' | 'active' | 'completed'

export interface AIPipelineStage {
  id: AIPipelineStageId
  label: string
  shortLabel: string
  icon: string
  description: string
}

// ─── Legacy alias (used internally by store) ──────────────────
export type PipelineStageId = NavStageId

export interface PipelineStage {
  id: NavStageId
  label: string
  shortLabel: string
  step: number
  icon: string
  description: string
}

// ─── File / Upload ────────────────────────────────────────────
export interface UploadedFile {
  id: string
  name: string
  size: number
  type: 'pdf' | 'docx' | 'txt' | 'unknown'
  status: 'queued' | 'uploading' | 'done' | 'error'
  progress?: number
  uploadedAt?: Date
}

export interface UploadState {
  jobDescription: UploadedFile | null
  resumes: UploadedFile[]
}

// ─── Weightage ────────────────────────────────────────────────
export interface WeightCriterion {
  id: string
  label: string
  description: string
  weight: number
  locked: boolean
  color?: string
  badgeBg?: string
  badgeText?: string
  iconBg?: string
  iconColor?: string
  icon?: string
}

// ─── Candidate / Scoring ──────────────────────────────────────
export type ScreeningStatus = 'screened' | 'pending' | 'rejected'

export interface ExtractedField {
  key: string
  label: string
  value: string | string[]
  confidence: number
}

export interface CandidateScore {
  criterionId: string
  label: string
  score: number
  weight: number
  weightedScore: number
}

export interface Candidate {
  id: string
  name: string
  email: string
  phone?: string
  currentTitle?: string
  location?: string
  resumeFile: string
  overallScore: number
  rank: number
  status: ScreeningStatus
  extractedFields: ExtractedField[]
  scores: CandidateScore[]
  aiExplanation?: string
  keyStrengths?: string[]
  keyWeaknesses?: string[]
  extractedAt?: Date
  scoredAt?: Date
}

// ─── Pipeline State ───────────────────────────────────────────
export interface PipelineState {
  currentStep: number
  completedSteps: number[]
  upload: UploadState
  weights: WeightCriterion[]
  candidates: Candidate[]
  scoringRunAt?: Date
  isProcessing: boolean
  aiPipelineStep: number   // 0 = not started, 1–7 = current AI stage, 8 = complete
  aiPipelineComplete: boolean
}

// ─── Navigation ───────────────────────────────────────────────
export interface BreadcrumbItem {
  label: string
  href?: string
}

// ─── User ─────────────────────────────────────────────────────
export interface AppUser {
  name: string
  role: string
  avatar?: string
  initials: string
}
