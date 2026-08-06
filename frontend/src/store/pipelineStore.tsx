import React, { createContext, useContext, useReducer, ReactNode } from 'react'
import { PipelineState, UploadedFile, Candidate, ScreeningStatus } from '@/types'
import { DEFAULT_WEIGHTS, MOCK_CANDIDATES, NAV_STAGES } from '@/constants'

// ─── Initial State ────────────────────────────────────────────
const initialState: PipelineState = {
  currentStep: 1,
  completedSteps: [],
  upload: { jobDescription: null, resumes: [] },
  weights: DEFAULT_WEIGHTS,
  candidates: [],
  isProcessing: false,
  aiPipelineStep: 0,
  aiPipelineComplete: false,
}

// ─── Actions ──────────────────────────────────────────────────
type Action =
  | { type: 'GO_TO_STEP'; payload: number }
  | { type: 'COMPLETE_STEP'; payload: number }
  | { type: 'SET_JD'; payload: UploadedFile | null }
  | { type: 'ADD_RESUMES'; payload: UploadedFile[] }
  | { type: 'REMOVE_RESUME'; payload: string }
  | { type: 'CLEAR_UPLOAD' }
  | { type: 'UPDATE_WEIGHT'; payload: { id: string; weight: number } }
  | { type: 'SET_PROCESSING'; payload: boolean }
  | { type: 'SET_AI_PIPELINE_STEP'; payload: number }
  | { type: 'COMPLETE_AI_PIPELINE' }
  | { type: 'RUN_SCORING' }
  | { type: 'UPDATE_CANDIDATE_STATUS'; payload: { id: string; status: ScreeningStatus } }

function reducer(state: PipelineState, action: Action): PipelineState {
  switch (action.type) {
    case 'GO_TO_STEP':
      return { ...state, currentStep: action.payload }

    case 'COMPLETE_STEP':
      return {
        ...state,
        completedSteps: state.completedSteps.includes(action.payload)
          ? state.completedSteps
          : [...state.completedSteps, action.payload],
      }

    case 'SET_JD':
      return {
        ...state,
        upload: { ...state.upload, jobDescription: action.payload },
      }

    case 'ADD_RESUMES':
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: [...state.upload.resumes, ...action.payload],
        },
      }

    case 'REMOVE_RESUME':
      return {
        ...state,
        upload: {
          ...state.upload,
          resumes: state.upload.resumes.filter((r) => r.id !== action.payload),
        },
      }

    case 'CLEAR_UPLOAD':
      return { ...state, upload: { jobDescription: null, resumes: [] } }

    case 'UPDATE_WEIGHT':
      return {
        ...state,
        weights: state.weights.map((w) =>
          w.id === action.payload.id ? { ...w, weight: action.payload.weight } : w
        ),
      }

    case 'SET_PROCESSING':
      return { ...state, isProcessing: action.payload }

    case 'SET_AI_PIPELINE_STEP':
      return { ...state, aiPipelineStep: action.payload, isProcessing: true }

    case 'COMPLETE_AI_PIPELINE':
      return {
        ...state,
        aiPipelineStep: 7,
        aiPipelineComplete: true,
        isProcessing: false,
        candidates: MOCK_CANDIDATES as Candidate[],
        scoringRunAt: new Date(),
      }

    case 'RUN_SCORING':
      return {
        ...state,
        candidates: MOCK_CANDIDATES as Candidate[],
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
  totalFiles: number
  canProceed: boolean
  canProceedJD: boolean
  canProceedResumes: boolean
}

const PipelineContext = createContext<PipelineContextValue | null>(null)

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const goToStep = (step: number) => dispatch({ type: 'GO_TO_STEP', payload: step })

  const completeAndAdvance = () => {
    dispatch({ type: 'COMPLETE_STEP', payload: state.currentStep })
    dispatch({ type: 'GO_TO_STEP', payload: Math.min(state.currentStep + 1, NAV_STAGES.length) })
  }

  const totalFiles =
    (state.upload.jobDescription ? 1 : 0) + state.upload.resumes.length

  const canProceedJD = state.upload.jobDescription !== null
  const canProceedResumes = state.upload.resumes.length > 0
  const canProceed = canProceedJD

  return (
    <PipelineContext.Provider
      value={{
        state,
        dispatch,
        goToStep,
        completeAndAdvance,
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
