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
  status: 'queued' | 'uploading' | 'processing' | 'done' | 'error'
  progress?: number
  uploadedAt?: Date
  /** Backend / processing error message shown in the file row. */
  errorMessage?: string
  /** Short label while status is uploading/processing (e.g. Parsing…). */
  statusLabel?: string
}

export interface UploadState {
  jobDescription: UploadedFile | null
  resumes: UploadedFile[]
}

// ─── Weightage (aligned with backend WeightDistribution) ──────
export type WeightCriterionId =
  | 'skills'
  | 'experience'
  | 'projects'
  | 'education'
  | 'certifications'
  | 'languages'

export interface WeightCriterion {
  id: WeightCriterionId
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

// ─── JD / document processing (mirrors backend document fields) ─
/** Backend ProcessingStatus values used by document pipelines. */
export type DocumentProcessingStatus =
  | 'UPLOADED'
  | 'PARSING_PENDING'
  | 'PARSED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'COMPLETED'

/** @deprecated Prefer DocumentProcessingStatus — kept for existing JD field names. */
export type JdProcessingStatus = DocumentProcessingStatus

/** Backend ProcessingStage values used by document pipelines. */
export type DocumentProcessingStage =
  | 'UPLOAD'
  | 'INGESTION'
  | 'PARSING'
  | 'EXTRACTION'
  | 'NORMALIZATION'
  | 'COMPLETED'
  | 'FAILED'

/** @deprecated Prefer DocumentProcessingStage — kept for existing JD field names. */
export type JdProcessingStage = DocumentProcessingStage

export type ResumeProcessingPhase =
  | 'uploaded'
  | 'parsing'
  | 'extracting'
  | 'normalizing'
  | 'normalized'
  | 'failed'

export interface ResumeProcessingState {
  documentId: string
  phase: ResumeProcessingPhase
  status: DocumentProcessingStatus | null
  stage: DocumentProcessingStage | null
  normalized: boolean
  errorMessage?: string
}

// ─── Pipeline State ───────────────────────────────────────────
export interface PipelineState {
  currentStep: number
  completedSteps: number[]
  /** Backend project UUID from POST /projects (JD upload flow). */
  projectId: string | null
  /** Backend JD document UUID from POST /projects/{id}/job-description. */
  jdDocumentId: string | null
  /** Latest backend processing_status for the JD document. */
  jdProcessingStatus: JdProcessingStatus | null
  /** Latest backend processing_stage for the JD document. */
  jdProcessingStage: JdProcessingStage | null
  /** True only after POST /documents/{id}/normalize succeeds for the JD. */
  jdNormalized: boolean
  /** True after POST /projects/{id}/weight-config succeeds for the current weights. */
  weightConfigSaved: boolean
  /** Backend weight-config UUID from the last successful save. */
  weightConfigId: string | null
  /** Backend document UUIDs for successfully batch-uploaded resumes. */
  resumeDocumentIds: string[]
  /** Per-resume parse → extract → normalize tracking keyed by document id. */
  resumeProcessing: Record<string, ResumeProcessingState>
  /** True after POST /projects/{id}/score succeeds. */
  scoringComplete: boolean
  /** Last scoring API error message, if any. */
  scoringError: string | null
  /**
   * Raw scoring payload from POST /projects/{id}/score.
   * Shape matches api ProjectScoring (project_id, total_evaluated, scores[]).
   */
  projectScoring: {
    project_id: string
    total_evaluated: number
    scores: Array<{
      id: string
      document_id: string
      project_id: string
      final_score: number
      confidence: number
      recommendation: string
      is_knocked_out: boolean
      knockout_reason: string | null
      strengths: string[]
      weaknesses: string[]
      matched_skills: string[]
      missing_skills: string[]
      skills_score: number
      experience_score: number
      projects_score: number
      education_score: number
      certifications_score: number
      languages_score: number
      component_scores: {
        skills: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
        experience: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
        projects: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
        education: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
        certifications: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
        languages: { score: number; matched_items: string[]; missing_items: string[]; explanation: string }
      }
      weighted_scores: {
        skills: number
        experience: number
        projects: number
        education: number
        certifications: number
        languages: number
      }
      created_at: string
      updated_at: string
    }>
  } | null
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
