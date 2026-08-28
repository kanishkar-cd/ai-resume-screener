/**
 * Minimal reusable API client for the FastAPI `/api/v1` backend.
 * UI components are not wired here — call these from pages/store later.
 */
import { apiRequest } from './client'
import type {
  AssessmentHandoffData,
  AssessmentStatusResponse,
  BatchResumeUpload,
  CandidateInsights,
  CandidateRanking,
  CandidateScore,
  Document,
  DocumentUpload,
  DocumentList,
  ExtractedDocument,
  ExtractResult,
  NormalizeResult,
  NormalizedDocument,
  Paginated,
  ParseResult,
  ParsedDocument,
  PipelineStatusResponse,
  Project,
  ProjectAnalytics,
  ProjectCreate,
  ProjectList,
  ProjectUpdate,
  ProjectDashboard,
  ProjectScoring,
  RankingComputation,
  RankingsQuery,
  WeightConfig,
  WeightConfigCreate,
  WeightConfigUpdate,
} from './types'

export * from './types'
export { ApiError, getApiBaseUrl } from './client'

export const api = {
  // ── Projects ──────────────────────────────────────────────
  createProject(payload: ProjectCreate): Promise<Project> {
    return apiRequest<Project>('/projects', { method: 'POST', body: payload })
  },

  listProjects(): Promise<ProjectList> {
    return apiRequest<ProjectList>('/projects', {}, { page_size: 100 })
  },

  getProject(projectId: string): Promise<Project> {
    return apiRequest<Project>(`/projects/${projectId}`)
  },

  updateProject(projectId: string, payload: ProjectUpdate): Promise<Project> {
    return apiRequest<Project>(`/projects/${projectId}`, { method: 'PATCH', body: payload })
  },

  deleteProject(projectId: string): Promise<void> {
    return apiRequest<void>(`/projects/${projectId}`, { method: 'DELETE' })
  },

  // ── JD upload ─────────────────────────────────────────────
  uploadJobDescription(projectId: string, file: File): Promise<DocumentUpload> {
    const form = new FormData()
    form.append('file', file)
    return apiRequest<DocumentUpload>(`/projects/${projectId}/job-description`, {
      method: 'POST',
      body: form,
      isMultipart: true,
    })
  },

  getJobDescription(projectId: string): Promise<Document> {
    return apiRequest<Document>(`/projects/${projectId}/job-description`)
  },

  // ── Resume batch upload ───────────────────────────────────
  uploadResumeBatch(projectId: string, files: File[]): Promise<BatchResumeUpload> {
    const form = new FormData()
    for (const file of files) {
      form.append('files', file)
    }
    return apiRequest<BatchResumeUpload>(`/projects/${projectId}/resumes/batch`, {
      method: 'POST',
      body: form,
      isMultipart: true,
    })
  },

  listProjectResumes(projectId: string): Promise<DocumentList> {
    return apiRequest<DocumentList>(`/projects/${projectId}/resumes`, {}, { page_size: 100 })
  },

  /** GET /documents/{document_id} — used to poll processing_status after parse. */
  getDocument(documentId: string): Promise<Document> {
    return apiRequest<Document>(`/documents/${documentId}`)
  },

  // ── Parse ─────────────────────────────────────────────────
  parseDocument(documentId: string): Promise<ParseResult> {
    return apiRequest<ParseResult>(`/documents/${documentId}/parse`, { method: 'POST' })
  },

  getParsedDocument(documentId: string): Promise<ParsedDocument> {
    return apiRequest<ParsedDocument>(`/documents/${documentId}/parsed`)
  },

  // ── Extract ───────────────────────────────────────────────
  extractDocument(documentId: string): Promise<ExtractResult> {
    return apiRequest<ExtractResult>(`/documents/${documentId}/extract`, { method: 'POST' })
  },

  getExtractedDocument(documentId: string): Promise<ExtractedDocument> {
    return apiRequest<ExtractedDocument>(`/documents/${documentId}/extracted`)
  },

  // ── Normalize ─────────────────────────────────────────────
  normalizeDocument(documentId: string): Promise<NormalizeResult> {
    return apiRequest<NormalizeResult>(`/documents/${documentId}/normalize`, {
      method: 'POST',
    })
  },

  getNormalizedDocument(documentId: string): Promise<NormalizedDocument> {
    return apiRequest<NormalizedDocument>(`/documents/${documentId}/normalized`)
  },

  // ── Weight config ─────────────────────────────────────────
  createWeightConfig(projectId: string, payload: WeightConfigCreate): Promise<WeightConfig> {
    return apiRequest<WeightConfig>(`/projects/${projectId}/weight-config`, {
      method: 'POST',
      body: payload,
    })
  },

  getWeightConfig(projectId: string): Promise<WeightConfig> {
    return apiRequest<WeightConfig>(`/projects/${projectId}/weight-config`)
  },

  updateWeightConfig(projectId: string, payload: WeightConfigUpdate): Promise<WeightConfig> {
    return apiRequest<WeightConfig>(`/projects/${projectId}/weight-config`, {
      method: 'PATCH',
      body: payload,
    })
  },

  // ── Score ─────────────────────────────────────────────────
  scoreProject(projectId: string): Promise<ProjectScoring> {
    return apiRequest<ProjectScoring>(`/projects/${projectId}/score`, { method: 'POST' })
  },

  scoreDocument(projectId: string, documentId: string): Promise<CandidateScore> {
    return apiRequest<CandidateScore>(
      `/projects/${projectId}/documents/${documentId}/score`,
      { method: 'POST' },
    )
  },

  getProjectScores(projectId: string): Promise<CandidateScore[]> {
    return apiRequest<CandidateScore[]>(`/projects/${projectId}/scores`)
  },

  // ── Rank / rankings ───────────────────────────────────────
  rankProject(projectId: string): Promise<RankingComputation> {
    return apiRequest<RankingComputation>(`/projects/${projectId}/rank`, { method: 'POST' })
  },

  getRankings(projectId: string, query?: RankingsQuery): Promise<Paginated<CandidateRanking>> {
    return apiRequest<Paginated<CandidateRanking>>(
      `/projects/${projectId}/rankings`,
      {},
      query as Record<string, string | number | boolean | undefined | null> | undefined,
    )
  },

  // ── Dashboard & Analytics ──────────────────────────────────
  getDashboard(projectId: string): Promise<ProjectDashboard> {
    return apiRequest<ProjectDashboard>(`/projects/${projectId}/dashboard`)
  },

  getAnalytics(projectId: string): Promise<ProjectAnalytics> {
    return apiRequest<ProjectAnalytics>(`/projects/${projectId}/analytics`)
  },

  getPipelineStatus(projectId: string): Promise<PipelineStatusResponse> {
    return apiRequest<PipelineStatusResponse>(`/projects/${projectId}/pipeline-status`)
  },

  getInsights(documentId: string): Promise<CandidateInsights> {
    return apiRequest<CandidateInsights>(`/documents/${documentId}/insights`)
  },

  handoffAssessment(projectId: string, candidateIds: string[], requisitionRef: string): Promise<AssessmentHandoffData> {
    return apiRequest<AssessmentHandoffData>(`/projects/${projectId}/assessment/handoff`, {
      method: 'POST',
      body: { candidate_ids: candidateIds, requisition_ref: requisitionRef },
    })
  },

  getAssessmentStatus(projectId: string): Promise<AssessmentStatusResponse> {
    return apiRequest<AssessmentStatusResponse>(`/projects/${projectId}/assessment/status`)
  },


  async exportProjectData(projectId: string, format: 'csv' | 'excel' | 'json' | 'pdf'): Promise<Blob> {
    const res = await apiRequest<Response>(`/projects/${projectId}/export/${format}`, { raw: true })
    return res.blob()
  },
}
