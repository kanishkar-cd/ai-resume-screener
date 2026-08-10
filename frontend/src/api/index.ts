/**
 * Minimal reusable API client for the FastAPI `/api/v1` backend.
 * UI components are not wired here — call these from pages/store later.
 */
import { apiRequest } from './client'
import type {
  BatchResumeUpload,
  CandidateRanking,
  CandidateScore,
  Document,
  DocumentUpload,
  ExtractedDocument,
  ExtractResult,
  NormalizeResult,
  NormalizedDocument,
  Paginated,
  ParseResult,
  ParsedDocument,
  Project,
  ProjectCreate,
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

  // ── JD upload ─────────────────────────────────────────────
  uploadJobDescription(projectId: string, file: File): Promise<DocumentUpload> {
    const form = new FormData()
    form.append('project_id', projectId)
    form.append('document_type', 'JOB_DESCRIPTION')
    form.append('file', file)
    return apiRequest<DocumentUpload>(`/documents/upload`, {
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

  // ── Dashboard ─────────────────────────────────────────────
  getDashboard(projectId: string): Promise<ProjectDashboard> {
    return apiRequest<ProjectDashboard>(`/projects/${projectId}/dashboard`)
  },
}
