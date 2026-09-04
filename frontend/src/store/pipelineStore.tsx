import React, { createContext, useContext, useEffect, useReducer, ReactNode } from 'react'
import {
  PipelineState,
  UploadedFile,
  Candidate,
  ScreeningStatus,
  JdProcessingStatus,
  JdProcessingStage,
  ResumeProcessingState,
} from '@/types'
import { DEFAULT_WEIGHTS, NAV_STAGES } from '@/constants'

// ─── Initial State ────────────────────────────────────────────

const PIPELINE_SESSION_STORAGE_KEY = 'ai-resume-screener.pipeline-session'
const LEGACY_PROJECT_STORAGE_KEY = 'ai-resume-screener.active-project-id'

const emptyState: PipelineState = {
  currentStep: 1,
  completedSteps: [],
  projectId: null,
  selectedProject: null,
  jdDocumentId: null,
  jdProcessingStatus: null,
  jdProcessingStage: null,
  jdNormalized: false,
  weightConfigSaved: false,
  weightConfigId: null,
  resumeDocumentIds: [],
  resumeProcessing: {},
  scoringComplete: false,
  scoringError: null,
  projectScoring: null,
  upload: { jobDescription: null, resumes: [] },
  weights: DEFAULT_WEIGHTS,
  candidates: [],
  isProcessing: false,
  aiPipelineStep: 0,
  aiPipelineComplete: false,
  activeDepartmentId: null,
  shortlistedCandidateIds: [],
  assessmentCandidates: [],
}

function restorePipelineState(): PipelineState {
  if (typeof window === 'undefined') return emptyState
  const raw = window.sessionStorage.getItem(PIPELINE_SESSION_STORAGE_KEY)
  if (!raw) return emptyState
  try {
    const restored = JSON.parse(raw) as PipelineState
    return {
      ...emptyState,
      ...restored,
      isProcessing: false,
      upload: {
        jobDescription: restored.upload?.jobDescription
          ? {
            ...restored.upload.jobDescription,
            uploadedAt: restored.upload.jobDescription.uploadedAt
              ? new Date(restored.upload.jobDescription.uploadedAt)
              : undefined,
          }
          : null,
        resumes: (restored.upload?.resumes ?? []).map((resume: any) => ({
          ...resume,
          uploadedAt: resume.uploadedAt ? new Date(resume.uploadedAt) : undefined,
        })),
      },
      candidates: restored.candidates ?? [],
      assessmentCandidates: restored.assessmentCandidates ?? [],
      shortlistedCandidateIds: restored.shortlistedCandidateIds ?? [],
      scoringComplete: true,
      scoringRunAt: restored.scoringRunAt ? new Date(restored.scoringRunAt) : undefined,
    }
  } catch {
    window.sessionStorage.removeItem(PIPELINE_SESSION_STORAGE_KEY)
    return emptyState
  }
}

// ─── Actions ──────────────────────────────────────────────────
type Action =
  | { type: 'GO_TO_STEP'; payload: number }
  | { type: 'RESET_PIPELINE' }
  | { type: 'COMPLETE_STEP'; payload: number }
  | { type: 'SET_PROJECT_ID'; payload: string }
  | { type: 'SELECT_PROJECT'; payload: NonNullable<PipelineState['selectedProject']> }
  | { type: 'SET_JD_DOCUMENT_ID'; payload: string | null }
  | {
    type: 'SET_JD_PROCESSING'
    payload: {
      status?: JdProcessingStatus | null
      stage?: JdProcessingStage | null
      normalized?: boolean
    }
  }
  | { type: 'SET_JD'; payload: UploadedFile | null }
  | { type: 'ADD_RESUMES'; payload: UploadedFile[] }
  | { type: 'SET_RESUMES'; payload: UploadedFile[] }
  | { type: 'REMOVE_RESUME'; payload: string }
  | {
    type: 'UPDATE_RESUME'
    payload: { id: string; patch: Partial<UploadedFile> }
  }
  | {
    type: 'UPSERT_RESUME_PROCESSING'
    payload: ResumeProcessingState
  }
  | { type: 'CLEAR_UPLOAD' }
  | { type: 'UPDATE_WEIGHT'; payload: { id: string; weight: number } }
  | {
    type: 'SET_WEIGHT_CONFIG_SAVED'
    payload: { saved: boolean; weightConfigId?: string | null }
  }
  | {
    type: 'SET_SCORING_RESULT'
    payload: {
      scoring: PipelineState['projectScoring']
      candidates: Candidate[]
    }
  }
  | { type: 'REMOVE_RESUME'; payload: string }
  | {
    type: 'UPDATE_RESUME'
    payload: { id: string; patch: Partial<UploadedFile> }
  }
  | {
    type: 'UPSERT_RESUME_PROCESSING'
    payload: ResumeProcessingState
  }
  | { type: 'CLEAR_UPLOAD' }
  | { type: 'UPDATE_WEIGHT'; payload: { id: string; weight: number } }
  | {
    type: 'SET_WEIGHT_CONFIG_SAVED'
    payload: { saved: boolean; weightConfigId?: string | null }
  }
  | {
    type: 'SET_SCORING_RESULT'
    payload: {
      scoring: PipelineState['projectScoring']
      candidates: Candidate[]
    }
  }
  | { type: 'SET_SCORING_ERROR'; payload: string | null }
  | { type: 'SET_RANKED_CANDIDATES'; payload: Candidate[] }
  | { type: 'SET_PROCESSING'; payload: boolean }
  | { type: 'SET_AI_PIPELINE_STEP'; payload: number }
  | { type: 'COMPLETE_AI_PIPELINE' }
  | { type: 'RUN_SCORING' }
  | { type: 'UPDATE_CANDIDATE_STATUS'; payload: { id: string; status: ScreeningStatus } }
  | { type: 'SET_DEPARTMENT_ID'; payload: string | null }
  | { type: 'TOGGLE_SHORTLIST_CANDIDATE'; payload: string }
  | { type: 'SET_SHORTLIST_CANDIDATES'; payload: string[] }
  | {
    type: 'SEND_TO_ASSESSMENT'
    payload: {
      candidateIds: string[]
      reqRef: string
      linksMap?: Record<string, string | null>
    }
  }
  | {
    type: 'UPDATE_ASSESSMENT_RESULTS'
    payload: {
      reqRef?: string
      results: Array<{
        candidateId?: string
        externalCandidateRef?: string
        email?: string
        sessionStatus?: string
        scoreStatus?: string
        compositeScore?: number | null
        compositeScoreBand?: string | null
        identityStatus?: string | null
        isIdentityVerified?: boolean | null
        startedAt?: string | null
        submittedAt?: string | null
        expiresAt?: string | null
        decision?: string | null
        assessmentLink?: string | null
      }>
    }
  }

function reducer(state: PipelineState, action: Action): PipelineState {
  switch (action.type) {
    case 'SET_DEPARTMENT_ID':
      return { ...state, activeDepartmentId: action.payload }

    case 'TOGGLE_SHORTLIST_CANDIDATE': {
      const current = state.shortlistedCandidateIds || []
      const exists = current.includes(action.payload)
      const next = exists ? current.filter((id) => id !== action.payload) : [...current, action.payload]
      return { ...state, shortlistedCandidateIds: next }
    }

    case 'SET_SHORTLIST_CANDIDATES':
      return { ...state, shortlistedCandidateIds: action.payload }

    case 'SEND_TO_ASSESSMENT': {
      const existing = state.assessmentCandidates || []
      const candidatesMap = new Map(state.candidates.map((c) => [c.id, c]))
      const newItems = action.payload.candidateIds.map((cid) => {
        const c = candidatesMap.get(cid)
        return {
          id: cid,
          candidateName: c?.name || 'Candidate',
          email: c?.email || '',
          currentTitle: c?.currentTitle || 'Applicant',
          reqRef: action.payload.reqRef,
          meritScore: c?.overallScore || 0,
          rank: c?.rank || 0,
          status: 'Sent' as const,
          sessionStatus: 'not_started',
          scoreStatus: 'not_graded',
          compositeScore: null,
          compositeScoreBand: null,
          sentAt: new Date().toLocaleDateString(),
          assessmentLink: action.payload.linksMap?.[cid] || null,
        }
      })
      const merged = [...existing]
      for (const item of newItems) {
        const existingIdx = merged.findIndex((m) => m.id === item.id)
        if (existingIdx >= 0) {
          merged[existingIdx] = { ...merged[existingIdx], ...item }
        } else {
          merged.push(item)
        }
      }
      return { ...state, assessmentCandidates: merged }
    }

    case 'UPDATE_ASSESSMENT_RESULTS': {
      const results = action.payload.results || []
      if (results.length === 0) {
        return state
      }
      const existing = state.assessmentCandidates || []
      const candidatesMap = new Map(state.candidates.map((c) => [c.id, c]))
      const merged = [...existing]

      for (const res of results) {
        const targetId = res.candidateId || res.externalCandidateRef || (res as any).id
        const existingIdx = merged.findIndex(
          (m) => m.id === targetId || (m.candidateName && m.candidateName === (res as any).candidateName)
        )

        let scoreVal: number | null = null
        const rawScore = res.compositeScore !== undefined && res.compositeScore !== null
          ? res.compositeScore
          : ((res as any).composite_score !== undefined && (res as any).composite_score !== null
            ? (res as any).composite_score
            : ((res as any).compositescore !== undefined && (res as any).compositescore !== null
              ? (res as any).compositescore
              : (res as any).score))

        if (rawScore !== undefined && rawScore !== null && rawScore !== '') {
          const num = Number(rawScore)
          if (!isNaN(num)) {
            scoreVal = num > 0 && num <= 1 ? Math.round(num * 1000) / 10 : Math.round(num * 10) / 10
          }
        }

        const bandVal = res.compositeScoreBand || (res as any).composite_score_band || (res as any).score_band || null
        const sessStatus = (res.sessionStatus || (res as any).session_status || 'not_started').toLowerCase()
        const c = targetId ? candidatesMap.get(targetId) : undefined

        const updatedItem = {
          id: targetId || (existingIdx >= 0 ? merged[existingIdx].id : `cand_${merged.length}`),
          candidateName: (res as any).candidateName || (res as any).name || c?.name || (existingIdx >= 0 ? merged[existingIdx].candidateName : 'Candidate'),
          email: res.email || c?.email || (existingIdx >= 0 ? merged[existingIdx].email : ''),
          currentTitle: c?.currentTitle || (existingIdx >= 0 ? merged[existingIdx].currentTitle : 'Applicant'),
          reqRef: action.payload.reqRef || (existingIdx >= 0 ? merged[existingIdx].reqRef : ''),
          meritScore: c?.overallScore || (existingIdx >= 0 ? merged[existingIdx].meritScore : 0),
          rank: c?.rank || (existingIdx >= 0 ? merged[existingIdx].rank : 1),
          status: (sessStatus === 'submitted' || sessStatus === 'completed') ? ('Submitted' as const) : ('Sent' as const),
          sentAt: (existingIdx >= 0 ? merged[existingIdx].sentAt : new Date().toLocaleDateString()),
          assessmentLink: res.assessmentLink || (res as any).assessment_link || (existingIdx >= 0 ? merged[existingIdx].assessmentLink : null),
          sessionStatus: sessStatus || (existingIdx >= 0 ? merged[existingIdx].sessionStatus : 'not_started'),
          scoreStatus: res.scoreStatus || (res as any).score_status || (scoreVal !== null ? 'graded' : (existingIdx >= 0 ? merged[existingIdx].scoreStatus : 'not_graded')),
          compositeScore: scoreVal !== null ? scoreVal : (existingIdx >= 0 ? merged[existingIdx].compositeScore : null),
          compositeScoreBand: bandVal || (existingIdx >= 0 ? merged[existingIdx].compositeScoreBand : null),
          identityStatus: res.identityStatus || (res as any).identity_status || (existingIdx >= 0 ? merged[existingIdx].identityStatus : null),
          isIdentityVerified: res.isIdentityVerified !== undefined ? res.isIdentityVerified : ((res as any).is_identity_verified ?? (existingIdx >= 0 ? merged[existingIdx].isIdentityVerified : null)),
          startedAt: res.startedAt || (res as any).started_at || (existingIdx >= 0 ? merged[existingIdx].startedAt : null),
          submittedAt: res.submittedAt || (res as any).submitted_at || (existingIdx >= 0 ? merged[existingIdx].submittedAt : null),
          expiresAt: res.expiresAt || (res as any).expires_at || (existingIdx >= 0 ? merged[existingIdx].expiresAt : null),
          decision: res.decision || (existingIdx >= 0 ? merged[existingIdx].decision : null),
        }

        if (existingIdx >= 0) {
          merged[existingIdx] = { ...merged[existingIdx], ...updatedItem }
        } else {
          merged.push(updatedItem as any)
        }
      }

      return { ...state, assessmentCandidates: merged }
    }

    case 'RESET_PIPELINE':
      return { ...emptyState, weights: DEFAULT_WEIGHTS.map((weight) => ({ ...weight })) }

    case 'COMPLETE_STEP':
      return {
        ...state,
        completedSteps: state.completedSteps.includes(action.payload)
          ? state.completedSteps
          : [...state.completedSteps, action.payload],
      }

    case 'SET_PROJECT_ID':
      return { ...state, projectId: action.payload }

    case 'SELECT_PROJECT':
      if (state.projectId === action.payload.id) {
        return { ...state, projectId: action.payload.id, selectedProject: action.payload }
      }
      return {
        ...emptyState,
        projectId: action.payload.id,
        selectedProject: action.payload,
        weights: DEFAULT_WEIGHTS.map((weight) => ({ ...weight })),
      }

    case 'SET_JD_DOCUMENT_ID':
      return { ...state, jdDocumentId: action.payload }

    case 'SET_JD_PROCESSING':
      return {
        ...state,
        jdProcessingStatus:
          action.payload.status !== undefined
            ? action.payload.status
            : state.jdProcessingStatus,
        jdProcessingStage:
          action.payload.stage !== undefined
            ? action.payload.stage
            : state.jdProcessingStage,
        jdNormalized:
          action.payload.normalized !== undefined
            ? action.payload.normalized
            : state.jdNormalized,
      }

    case 'SET_JD':
      return {
        ...state,
        upload: { ...state.upload, jobDescription: action.payload },
        jdDocumentId:
          action.payload === null ? null : state.jdDocumentId,
        ...(action.payload === null
          ? {
            jdProcessingStatus: null,
            jdProcessingStage: null,
            jdNormalized: false,
          }
          : {}),
      }

    case 'ADD_RESUMES': {
      const successfulIds = action.payload
        .filter((r) => r.status === 'done')
        .map((r) => r.id)
      const nextProcessing = { ...state.resumeProcessing }
      for (const id of successfulIds) {
        if (!nextProcessing[id]) {
          nextProcessing[id] = {
            documentId: id,
            phase: 'uploaded',
            status: 'UPLOADED',
            stage: 'INGESTION',
            normalized: false,
          }
        }
      }
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: [...state.upload.resumes, ...action.payload],
        },
        resumeDocumentIds: [
          ...state.resumeDocumentIds,
          ...successfulIds.filter((id) => !state.resumeDocumentIds.includes(id)),
        ],
        resumeProcessing: nextProcessing,
      }
    }

    case 'SET_RESUMES': {
      const ids = action.payload.map((resume) => resume.id)
      const nextProcessing = { ...state.resumeProcessing }
      for (const resume of action.payload) {
        if (!nextProcessing[resume.id]) {
          nextProcessing[resume.id] = {
            documentId: resume.id,
            phase: resume.status === 'error' ? 'failed' : 'uploaded',
            status: resume.status === 'error' ? 'FAILED' : 'UPLOADED',
            stage: resume.status === 'error' ? 'FAILED' : 'INGESTION',
            normalized: false,
            errorMessage: resume.errorMessage,
          }
        }
      }
      return {
        ...state,
        upload: { ...state.upload, resumes: action.payload },
        resumeDocumentIds: ids,
        resumeProcessing: nextProcessing,
      }
    }

    case 'REMOVE_RESUME': {
      const filteredResumes = state.upload.resumes.filter((r: UploadedFile) => r.id !== action.payload)
      const filteredIds = state.resumeDocumentIds.filter((id) => id !== action.payload)
      const filteredProcessing = { ...state.resumeProcessing }
      delete filteredProcessing[action.payload]
      return {
        ...state,
        upload: { ...state.upload, resumes: filteredResumes },
        resumeDocumentIds: filteredIds,
        resumeProcessing: filteredProcessing,
      }
    }

    case 'UPDATE_RESUME': {
      const { id, patch } = action.payload
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: state.upload.resumes.map((r: UploadedFile) =>
            r.id === id ? { ...r, ...patch } : r
          ),
        },
      }
    }

    case 'UPSERT_RESUME_PROCESSING': {
      const { documentId } = action.payload
      return {
        ...state,
        resumeProcessing: {
          ...state.resumeProcessing,
          [documentId]: {
            ...state.resumeProcessing[documentId],
            ...action.payload,
          },
        },
      }
    }

    case 'SET_SCORING_ERROR':
      return {
        ...state,
        scoringError: action.payload,
        scoringComplete: false,
        isProcessing: false,
      }

    case 'SET_PROCESSING':
      return { ...state, isProcessing: action.payload }

    case 'SET_RANKED_CANDIDATES':
      return { ...state, candidates: action.payload, scoringComplete: action.payload.length > 0, scoringError: null, isProcessing: false }

    case 'SET_AI_PIPELINE_STEP':
      return { ...state, aiPipelineStep: action.payload, isProcessing: true }

    case 'COMPLETE_AI_PIPELINE':
      return {
        ...state,
        aiPipelineStep: 7,
        aiPipelineComplete: true,
        isProcessing: false,
        scoringRunAt: new Date(),
      }

    case 'RUN_SCORING':
      return {
        ...state,
        scoringRunAt: new Date(),
        isProcessing: false,
      }

    case 'UPDATE_CANDIDATE_STATUS':
      return {
        ...state,
        candidates: state.candidates.map((c) =>
          c.id === action.payload.id ? { ...c, status: action.payload.status } : c
        ),
      }

    default:
      return state
  }
}

// ─── Context ──────────────────────────────────────────────────
interface PipelineContextValue {
  state: PipelineState
  dispatch: React.Dispatch<Action>
  goToStep: (step: number) => void
  completeAndAdvance: () => void
  startNewScreening: () => void
  totalFiles: number
  canProceed: boolean
  canProceedJD: boolean
  canProceedResumes: boolean
}

const PipelineContext = createContext<PipelineContextValue | null>(null)

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, restorePipelineState)

  useEffect(() => {
    window.sessionStorage.removeItem(LEGACY_PROJECT_STORAGE_KEY)
    window.sessionStorage.setItem(PIPELINE_SESSION_STORAGE_KEY, JSON.stringify(state))
  }, [state])

  const goToStep = (step: number) => dispatch({ type: 'GO_TO_STEP', payload: step })

  const completeAndAdvance = () => {
    dispatch({ type: 'COMPLETE_STEP', payload: state.currentStep })
    dispatch({ type: 'GO_TO_STEP', payload: Math.min(state.currentStep + 1, NAV_STAGES.length) })
  }

  const startNewScreening = () => {
    window.sessionStorage.removeItem(PIPELINE_SESSION_STORAGE_KEY)
    window.sessionStorage.removeItem(LEGACY_PROJECT_STORAGE_KEY)
    dispatch({ type: 'RESET_PIPELINE' })
  }

  const totalFiles =
    (state.upload.jobDescription ? 1 : 0) + state.upload.resumes.length

  const canProceedJD =
    state.projectId !== null &&
    state.jdDocumentId !== null &&
    state.upload.jobDescription?.status === 'done' &&
    state.jdNormalized === true &&
    state.isProcessing === false

  // canProceedResumes: enable Continue whenever at least 1 resume is queued and
  // no active processing phase is running. In mock mode the normalization state
  // may not be set, so we fall back to checking upload.resumes for non-error items.
  const canProceedResumes = (() => {
    const queuedDone = state.upload.resumes.filter((r: any) => r.status !== 'error').length
    if (queuedDone === 0 && state.resumeDocumentIds.length === 0) return false
    const anyActivePhase = Object.values(state.resumeProcessing).some(
      (p) => p.phase === 'parsing' || p.phase === 'extracting' || p.phase === 'normalizing',
    )
    if (anyActivePhase) return false
    const allNormalized =
      state.resumeDocumentIds.length > 0 &&
      state.resumeDocumentIds.every((id) => state.resumeProcessing[id]?.normalized === true)
    return allNormalized || queuedDone > 0
  })()

  const canProceed = canProceedJD

  return (
    <PipelineContext.Provider
      value={{
        state,
        dispatch,
        goToStep,
        completeAndAdvance,
        startNewScreening,
        totalFiles,
        canProceed,
        canProceedJD,
        canProceedResumes,
      }}
    >
      {children}
    </PipelineContext.Provider>
  )
}

export function usePipeline() {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider')
  return ctx
}
