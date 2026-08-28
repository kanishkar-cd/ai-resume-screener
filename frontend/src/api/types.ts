/**
 * Backend-aligned API types for `/api/v1`.
 * These interfaces mirror the FastAPI schemas.
 */

// ─── Shared / enums ───────────────────────────────────────────

export type ProjectStatus = 'DRAFT' | 'ACTIVE' | 'COMPLETED' | 'ARCHIVED'

export type DocumentType = 'RESUME' | 'JOB_DESCRIPTION'

export type ProcessingStage =
  | 'UPLOAD'
  | 'INGESTION'
  | 'PARSING'
  | 'EXTRACTION'
  | 'NORMALIZATION'
  | 'COMPLETED'
  | 'FAILED'

export type ProcessingStatus =
  | 'UPLOADED'
  | 'PARSING_PENDING'
  | 'PARSED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'COMPLETED'

export type RecommendationLevel = 'SHORTLIST' | 'REVIEW' | 'CONSIDER' | 'REJECT'

export type SortOrder = 'asc' | 'desc'

export type RankingSortField =
  | 'rank_position'
  | 'final_score'
  | 'skills_score'
  | 'experience_score'
  | 'confidence'
  | 'created_at'

export type ParserEngine = 'PYMUPDF' | 'PYTHON_DOCX' | 'PLAIN_TEXT'

// ─── Envelope / errors ────────────────────────────────────────

export interface ApiDataEnvelope<T> {
  data: T
}

export interface ApiErrorDetail {
  code: string
  message: string
  details: Record<string, unknown>
  timestamp: string
  correlation_id: string
}

export interface ApiErrorBody {
  error: ApiErrorDetail
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ─── Projects ─────────────────────────────────────────────────

export interface ProjectCreate {
  title: string
  description?: string | null
  target_role: string
  department?: string | null
  status?: ProjectStatus
  metadata_json?: Record<string, unknown>
}

export interface ProjectUpdate {
  title?: string
  description?: string | null
  target_role?: string
  department?: string | null
  status?: ProjectStatus
  metadata_json?: Record<string, unknown>
}

export interface Project {
  id: string
  title: string
  description: string | null
  target_role: string
  department: string | null
  status: ProjectStatus
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ProjectList = Paginated<Project>

// ─── Documents ────────────────────────────────────────────────

export interface DocumentUpload {
  document_id: string
  project_id: string
  document_type: DocumentType
  filename: string
  processing_stage: ProcessingStage
  processing_status: ProcessingStatus
}

export interface Document {
  id: string
  project_id: string
  document_type: DocumentType
  original_filename: string
  file_size_bytes: number
  mime_type: string
  file_hash: string
  processing_stage: ProcessingStage
  processing_status: ProcessingStatus
  error_message?: string | null
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type DocumentList = Paginated<Document>

export interface FailedUploadItem {
  original_filename: string
  error_code: string
  message: string
}

export interface BatchResumeUpload {
  project_id: string
  total_received: number
  successful_count: number
  failed_count: number
  successful_uploads: DocumentUpload[]
  failed_uploads: FailedUploadItem[]
}

// ─── Parse / extract / normalize ──────────────────────────────

export interface ParseResult {
  document_id: string
  processing_status: ProcessingStatus
  processing_stage: ProcessingStage
  message: string
}

export interface ParsedDocument {
  id: string
  document_id: string
  raw_text: string
  page_count: number | null
  word_count: number
  character_count: number
  parser_engine: ParserEngine
  parsing_duration_ms: number
  created_at: string
  updated_at: string
}

export interface EducationItem {
  degree?: string | null
  institution?: string | null
  year?: string | null
  field_of_study?: string | null
}

export interface ExperienceItem {
  company?: string | null
  title?: string | null
  designation?: string | null
  employment_type?: string | null
  start_date?: string | null
  end_date?: string | null
  duration?: string | null
  description?: string | null
  responsibilities?: string[]
}

export interface ProjectItem {
  name?: string | null
  description?: string | null
  technologies?: string[]
}

export interface ExtractedResume {
  id: string
  document_id: string
  candidate_name: string | null
  email: string | null
  phone: string | null
  designation: string | null
  location: string | null
  skills: string[]
  education: EducationItem[]
  experience: ExperienceItem[]
  projects: ProjectItem[]
  certifications: string[]
  companies: string[]
  languages: string[]
  confidence_scores: Record<string, number>
  raw_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ExtractedJobDescription {
  id: string
  document_id: string
  domain: string | null
  job_title: string | null
  skills: string[]
  required_skills: string[]
  preferred_skills: string[]
  responsibilities: string[]
  education: string[]
  education_disciplines: string[]
  experience: string[]
  certifications: string[]
  keywords: string[]
  confidence_scores: Record<string, number>
  raw_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ExtractedDocument = ExtractedResume | ExtractedJobDescription

export interface ExtractResult {
  processing_status: ProcessingStatus | null | undefined
  document_id: string
  document_type: DocumentType
  processing_stage: ProcessingStage
  message: string
}

export interface CanonicalEducationItem {
  degree?: string | null
  field_of_study?: string | null
  institution?: string | null
  graduation_date?: string | null
}

export interface CanonicalExperienceItem {
  company?: string | null
  job_title?: string | null
  start_date?: string | null
  end_date?: string | null
  is_current?: boolean
  duration_months?: number | null
  duration_display?: string | null
}

export interface CanonicalLocation {
  city?: string | null
  region?: string | null
  country?: string | null
  country_code?: string | null
  display_name: string
}

export interface CanonicalExperienceRequirement {
  minimum_months?: number | null
  maximum_months?: number | null
  display_value: string
}

export interface NormalizationChange {
  field: string
  source?: string | null
  canonical?: string | null
  rule: string
}

export interface NormalizationMetadata {
  ruleset_version: string
  normalized_at: string
  changes: NormalizationChange[]
  warnings: string[]
  field_confidence: Record<string, number>
}

export interface NormalizedResume {
  id: string
  document_id: string
  extracted_resume_id: string
  skills: string[]
  education: CanonicalEducationItem[]
  companies: string[]
  job_titles: string[]
  experience: CanonicalExperienceItem[]
  phone: string | null
  email: string | null
  locations: CanonicalLocation[]
  languages: string[]
  certifications: string[]
  normalization_metadata: NormalizationMetadata
  ruleset_version: string
  created_at: string
  updated_at: string
}

export interface NormalizedJobDescription {
  id: string
  document_id: string
  extracted_job_description_id: string
  skills: string[]
  job_title: string | null
  required_skills: string[]
  preferred_skills: string[]
  degree_requirements: string[]
  education_disciplines: string[]
  experience_requirements: CanonicalExperienceRequirement[]
  domain: string | null
  keywords: string[]
  responsibilities: string[]
  certifications: string[]
  normalization_metadata: NormalizationMetadata
  ruleset_version: string
  created_at: string
  updated_at: string
}

export type NormalizedDocument = NormalizedResume | NormalizedJobDescription

export interface NormalizeResult {
  processing_status: ProcessingStatus | null | undefined
  document_id: string
  document_type: DocumentType
  processing_stage: ProcessingStage
  ruleset_version: string
  message: string
}

// ─── Weight config ────────────────────────────────────────────

export interface WeightDistribution {
  skills: number
  experience: number
  projects: number
  education: number
  certifications: number
  languages: number
}

export interface KnockoutRule {
  rule_type: string
  enabled?: boolean
  description?: string | null
}

export interface WeightConfigCreate {
  weights?: WeightDistribution
  passing_score?: number
  min_experience_years?: number
  required_degree?: string | null
  required_certifications?: string[]
  mandatory_skills?: string[]
  preferred_skills?: string[]
  knockout_rules?: KnockoutRule[]
  custom_keywords?: string[]
}

export interface WeightConfigUpdate {
  weights?: WeightDistribution | null
  passing_score?: number | null
  min_experience_years?: number | null
  required_degree?: string | null
  required_certifications?: string[] | null
  mandatory_skills?: string[] | null
  preferred_skills?: string[] | null
  knockout_rules?: KnockoutRule[] | null
  custom_keywords?: string[] | null
}

export interface WeightConfig {
  id: string
  project_id: string
  weights: WeightDistribution
  passing_score: number
  min_experience_years: number
  required_degree: string | null
  required_certifications: string[]
  mandatory_skills: string[]
  preferred_skills: string[]
  knockout_rules: KnockoutRule[]
  custom_keywords: string[]
  version: number
  created_at: string
  updated_at: string
}

// ─── Scoring ──────────────────────────────────────────────────

export interface ComponentScoreDetail {
  score: number
  matched_items: string[]
  missing_items: string[]
  explanation: string
}

export interface ComponentScores {
  skills: ComponentScoreDetail
  experience: ComponentScoreDetail
  projects: ComponentScoreDetail
  education: ComponentScoreDetail
  certifications: ComponentScoreDetail
  languages: ComponentScoreDetail
}

export interface WeightedScores {
  skills: number
  experience: number
  projects: number
  education: number
  certifications: number
  languages: number
}

export interface AdjustmentItem {
  rule_name: string
  delta_points: number
  description: string
}

export type MatchVerdictStatus = 'MATCHED' | 'NO_MATCH' | 'UNRESOLVED'

export type MatchVerdictMethod = 'exact' | 'alias' | 'taxonomy' | 'llm_confirmed' | 'llm_rejected' | 'llm_unresolved'

export interface MatchVerdict {
  requirement_id: string
  status: MatchVerdictStatus
  confidence: number
  evidence_ids: string[]
  reasoning: string
  method: MatchVerdictMethod | null
}

export interface CategoryBreakdownItem {
  category: string
  component_score: number
  effective_weight: number
  contribution: number
  is_applicable: boolean
}

export interface CandidateScore {
  id: string
  document_id: string
  project_id: string
  component_scores: ComponentScores
  weighted_scores: WeightedScores
  raw_total_score: number
  weighted_total_score: number
  penalty_total: number
  bonus_total: number
  final_score: number
  confidence: number
  recommendation: RecommendationLevel
  is_knocked_out: boolean
  knockout_reason: string | null
  penalty_summary: AdjustmentItem[]
  bonus_summary: AdjustmentItem[]
  weight_config_version: number
  matched_skills: string[]
  missing_skills: string[]
  strengths: string[]
  weaknesses: string[]
  match_verdicts: MatchVerdict[]
  passing_score?: number
  effective_weights?: Record<string, number>
  score_breakdown?: CategoryBreakdownItem[]
  skills_score: number
  experience_score: number
  projects_score: number
  education_score: number
  created_at: string
  updated_at: string
}

export interface ProjectScoring {
  project_id: string
  total_evaluated: number
  scores: CandidateScore[]
}

// ─── Ranking ──────────────────────────────────────────────────

export interface CandidateRanking {
  id: string
  project_id: string
  document_id: string
  candidate_name: string
  email: string | null
  rank_position: number
  percentile: number
  final_score: number
  recommendation: RecommendationLevel
  confidence: number
  is_knocked_out: boolean
  knockout_reason: string | null
  skills_score: number
  experience_score: number
  previous_rank: number | null
  rank_change: number
  created_at: string
}

export interface RankingComputation {
  project_id: string
  total_ranked: number
  message: string
}

export interface RankingsQuery {
  page?: number
  page_size?: number
  recommendation?: RecommendationLevel
  min_score?: number
  max_score?: number
  is_knocked_out?: boolean
  search?: string
  sort_by?: RankingSortField
  order?: SortOrder
}

// ─── Dashboard ────────────────────────────────────────────────

export interface PipelineStageStatus {
  total_candidates: number
  candidates_ingested: number
  candidates_parsed: number
  candidates_extracted: number
  candidates_normalized: number
  candidates_scored: number
  candidates_ranked: number
}

export interface SkillFrequencyItem {
  skill_name: string
  frequency_count: number
  percentage: number
}

export interface ProjectAnalytics {
  project_id: string
  total_candidates: number
  average_score: number
  highest_score: number
  lowest_score: number
  average_confidence: number
  recommendation_distribution: Record<string, number>
  top_matched_skills: SkillFrequencyItem[]
  top_missing_skills: SkillFrequencyItem[]
  knocked_out_count: number
  knocked_out_summary: Record<string, unknown>[]
}

export interface ProjectSummary {
  project_id: string
  project_title: string
  target_role: string
  total_candidates: number
}

export interface ProjectDashboard {
  project_summary: ProjectSummary
  pipeline_counts: PipelineStageStatus
  analytics: ProjectAnalytics
  top_candidates: Record<string, unknown>[]
  pipeline_completion_percentage: number
  processing_time_seconds: number
  last_updated: string
}

export interface CandidateInsights {
  id: string
  document_id: string
  project_id: string
  summary: string
  strengths: string[]
  weaknesses: string[]
  matched_skills: string[]
  missing_skills: string[]
  score_explanation: string
  recommendation_reason: string
  created_at: string
  updated_at: string
}

export interface ProjectScoring {
  project_id: string
  total_evaluated: number
  scores: CandidateScore[]
}

// ─── Ranking ──────────────────────────────────────────────────

export interface CandidateRanking {
  id: string
  project_id: string
  document_id: string
  candidate_name: string
  email: string | null
  rank_position: number
  percentile: number
  final_score: number
  recommendation: RecommendationLevel
  confidence: number
  is_knocked_out: boolean
  knockout_reason: string | null
  skills_score: number
  experience_score: number
  previous_rank: number | null
  rank_change: number
  created_at: string
}

export interface RankingComputation {
  project_id: string
  total_ranked: number
  message: string
}

export interface RankingsQuery {
  page?: number
  page_size?: number
  recommendation?: RecommendationLevel
  min_score?: number
  max_score?: number
  is_knocked_out?: boolean
  search?: string
  sort_by?: RankingSortField
  order?: SortOrder
}

// ─── Dashboard ────────────────────────────────────────────────

export interface PipelineStageStatus {
  total_candidates: number
  candidates_ingested: number
  candidates_parsed: number
  candidates_extracted: number
  candidates_normalized: number
  candidates_scored: number
  candidates_ranked: number
}

export interface SkillFrequencyItem {
  skill_name: string
  frequency_count: number
  percentage: number
}

export interface ProjectAnalytics {
  project_id: string
  total_candidates: number
  average_score: number
  highest_score: number
  lowest_score: number
  average_confidence: number
  recommendation_distribution: Record<string, number>
  top_matched_skills: SkillFrequencyItem[]
  top_missing_skills: SkillFrequencyItem[]
  knocked_out_count: number
  knocked_out_summary: Record<string, unknown>[]
}

export interface ProjectSummary {
  project_id: string
  project_title: string
  target_role: string
  total_candidates: number
}

export interface ProjectDashboard {
  project_summary: ProjectSummary
  pipeline_counts: PipelineStageStatus
  analytics: ProjectAnalytics
  top_candidates: Record<string, unknown>[]
  pipeline_completion_percentage: number
  processing_time_seconds: number
  last_updated: string
}

export interface CandidateInsights {
  id: string
  document_id: string
  project_id: string
  summary: string
  strengths: string[]
  weaknesses: string[]
  matched_skills: string[]
  missing_skills: string[]
  score_explanation: string
  recommendation_reason: string
  improvement_suggestions: string[]
  created_at: string
  updated_at: string
}

export interface PipelineStatusResponse {
  project_id: string
  current_stage: ProcessingStage
  completed_stages: ProcessingStage[]
  remaining_stages: ProcessingStage[]
  resume_count: number
  stage_counts: Record<string, number>
  completion_percentage: number
}

// ─── Assessment Handoff ───────────────────────────────────────

export interface AssessmentHandoffRequest {
  candidate_ids: string[]
  requisition_ref: string
}

export interface CandidateAssessmentItem {
  candidate_id: string
  candidate_name?: string
  email?: string
  assessment_link: string | null
  status?: string
  session_status?: string
  sessionstatus?: string
  score_status?: string
  scorestatus?: string
  composite_score?: number | null
  compositescore?: number | null
  composite_score_band?: string | null
  compositescoreband?: string | null
  score_band?: string | null
  scoreband?: string | null
  identity_status?: string | null
  identitystatus?: string | null
  is_identity_verified?: boolean | null
  isidentityverified?: boolean | null
  started_at?: string | null
  startedat?: string | null
  submitted_at?: string | null
  submittedat?: string | null
  expires_at?: string | null
  expiresat?: string | null
  decision?: string | null
  external_candidate_ref?: string | null
}

export interface AssessmentHandoffData {
  project_id: string
  requisition_ref: string
  total_invited: number
  candidates: CandidateAssessmentItem[]
}

export interface AssessmentStatusResponse {
  requisition_ref?: string
  drive_id?: string | null
  session_status?: string
  score_status?: string
  composite_score?: number | null
  composite_score_band?: string | null
  decision?: string | null
  candidates?: CandidateAssessmentItem[]
}
