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
        resumes: (restored.upload?.resumes ?? []).map((resume) => ({
          ...resume,
          uploadedAt: resume.uploadedAt ? new Date(resume.uploadedAt) : undefined,
        })),
      },
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
  | { type: 'SET_SCORING_ERROR'; payload: string | null }
  | { type: 'SET_RANKED_CANDIDATES'; payload: Candidate[] }
  | { type: 'SET_PROCESSING'; payload: boolean }
  | { type: 'SET_AI_PIPELINE_STEP'; payload: number }
  | { type: 'COMPLETE_AI_PIPELINE' }
  | { type: 'RUN_SCORING' }
  | { type: 'UPDATE_CANDIDATE_STATUS'; payload: { id: string; status: ScreeningStatus } }

function reducer(state: PipelineState, action: Action): PipelineState {
  switch (action.type) {
    case 'RESET_PIPELINE':
      return { ...emptyState, weights: DEFAULT_WEIGHTS.map((weight) => ({ ...weight })) }

    case 'GO_TO_STEP':
      return { ...state, currentStep: action.payload }

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
      const { [action.payload]: _removed, ...restProcessing } = state.resumeProcessing
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: state.upload.resumes.filter((r) => r.id !== action.payload),
        },
        resumeDocumentIds: state.resumeDocumentIds.filter((id) => id !== action.payload),
        resumeProcessing: restProcessing,
      }
    }

    case 'UPDATE_RESUME':
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: state.upload.resumes.map((r) =>
            r.id === action.payload.id ? { ...r, ...action.payload.patch } : r
          ),
        },
      }

    case 'UPSERT_RESUME_PROCESSING':
      return {
        ...state,
        resumeProcessing: {
          ...state.resumeProcessing,
          [action.payload.documentId]: action.payload,
        },
      }

    case 'CLEAR_UPLOAD':
      return {
        ...state,
        jdDocumentId: null,
        jdProcessingStatus: null,
        jdProcessingStage: null,
        jdNormalized: false,
        resumeDocumentIds: [],
        resumeProcessing: {},
        upload: { jobDescription: null, resumes: [] },
      }

    case 'UPDATE_WEIGHT':
      return {
        ...state,
        weightConfigSaved: false,
        weightConfigId: null,
        weights: state.weights.map((w) =>
          w.id === action.payload.id ? { ...w, weight: action.payload.weight } : w
        ),
      }

    case 'SET_WEIGHT_CONFIG_SAVED':
      return {
        ...state,
        weightConfigSaved: action.payload.saved,
        weightConfigId:
          action.payload.weightConfigId !== undefined
            ? action.payload.weightConfigId
            : action.payload.saved
              ? state.weightConfigId
              : null,
      }

    case 'SET_SCORING_RESULT':
      return {
        ...state,
        projectScoring: action.payload.scoring,
        candidates: action.payload.candidates,
        scoringComplete: true,
        scoringError: null,
        scoringRunAt: new Date(),
        isProcessing: false,
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
  const canProceedResumes =
    state.resumeDocumentIds.length > 0 &&
    state.resumeDocumentIds.every(
      (id) => state.resumeProcessing[id]?.normalized === true,
    ) &&
    !Object.values(state.resumeProcessing).some((p) =>
      p.phase === 'parsing' || p.phase === 'extracting' || p.phase === 'normalizing',
    )
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
