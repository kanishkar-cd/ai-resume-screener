import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  FileText,
  Shield,
  Lightbulb,
  Check,
  ArrowRight,
  FileCheck,
} from 'lucide-react'
import UploadCard from '@/components/ui/UploadCard'
import { usePipeline } from '@/store/pipelineStore'
import { UploadedFile, JdProcessingStage, JdProcessingStatus } from '@/types'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/api'
import type { Document as ApiDocument, ExtractedJobDescription, NormalizedJobDescription, ParsedDocument } from '@/api'
import { JobProfile } from '@/components/ui/DocumentProfiles'

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
}

const container = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.08 },
  },
}

const PARSE_POLL_INTERVAL_MS = 1000
const PARSE_POLL_TIMEOUT_MS = 90_000

function fileTypeFromName(name: string): UploadedFile['type'] {
  const ext = name.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx' || ext === 'doc') return 'docx'
  if (ext === 'txt') return 'txt'
  return 'unknown'
}

/**
 * POST /projects requires title + target_role; Document Upload UI does not collect them.
 * Temporary placeholders so the JD upload flow can run — see mismatch notes in the PR/response.
 */
function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

function isParseTerminalSuccess(status: JdProcessingStatus): boolean {
  // Backend parse_document sets COMPLETED (not PARSED) on success.
  // Accept PARSED as well if an older path ever emits it.
  return status === 'COMPLETED' || status === 'PARSED'
}

function processingLabel(
  stage: JdProcessingStage | null,
  status: JdProcessingStatus | null,
  normalized: boolean,
  isProcessing: boolean,
): string {
  if (normalized) return 'JD normalized — ready for weightage'
  if (!isProcessing) {
    if (status === 'FAILED' || stage === 'FAILED') return 'JD processing failed'
    return 'No JD uploaded yet'
  }
  if (stage === 'PARSING' || status === 'IN_PROGRESS' || status === 'PARSING_PENDING') {
    return 'Parsing job description…'
  }
  if (stage === 'EXTRACTION') return 'Extracting JD fields…'
  if (stage === 'NORMALIZATION') return 'Normalizing JD data…'
  return 'Processing job description…'
}

export default function DocumentUpload() {
  const { state, dispatch, canProceedJD, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()
  const [flowError, setFlowError] = useState<string | null>(null)
  const [flowPhase, setFlowPhase] = useState<
    'idle' | 'uploading' | 'parsing' | 'extracting' | 'normalizing' | 'ready' | 'error'
  >('idle')
  const [profile, setProfile] = useState<{ normalized: NormalizedJobDescription; extracted: ExtractedJobDescription | null; parsed: ParsedDocument | null; document: ApiDocument } | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)
  const lookedUpProjectRef = useRef<string | null>(null)

  const busy =
    flowPhase === 'uploading' ||
    flowPhase === 'parsing' ||
    flowPhase === 'extracting' ||
    flowPhase === 'normalizing' ||
    state.isProcessing

  const updateJdProcessing = (payload: {
    status?: JdProcessingStatus | null
    stage?: JdProcessingStage | null
    normalized?: boolean
  }) => {
    dispatch({ type: 'SET_JD_PROCESSING', payload })
  }

  useEffect(() => {
    if (!state.projectId || state.jdDocumentId) return
    if (lookedUpProjectRef.current === state.projectId) return
    lookedUpProjectRef.current = state.projectId
    api.getJobDescription(state.projectId).then((document) => {
      dispatch({ type: 'SET_JD_DOCUMENT_ID', payload: document.id })
      dispatch({
        type: 'SET_JD',
        payload: {
          id: document.id,
          name: document.original_filename,
          size: document.file_size_bytes,
          type: fileTypeFromName(document.original_filename),
          status: document.processing_status === 'FAILED' ? 'error' : 'done',
          errorMessage: document.error_message ?? undefined,
          uploadedAt: new Date(document.created_at),
        },
      })
      updateJdProcessing({ status: document.processing_status, stage: document.processing_stage })
    }).catch(() => undefined)
  }, [dispatch, state.jdDocumentId, state.projectId])

  useEffect(() => {
    if (!state.jdDocumentId || !state.jdNormalized) {
      setProfile(null)
      return
    }
    let active = true
    Promise.all([
      api.getNormalizedDocument(state.jdDocumentId),
      api.getExtractedDocument(state.jdDocumentId).catch(() => null),
      api.getParsedDocument(state.jdDocumentId).catch(() => null),
      api.getDocument(state.jdDocumentId),
    ]).then(([normalized, extracted, parsed, document]) => {
      if (!active || !('degree_requirements' in normalized)) return
      setProfile({ normalized, extracted: extracted && 'responsibilities' in extracted ? extracted : null, parsed, document })
      setProfileError(null)
    }).catch((err) => {
      if (active) setProfileError(errorMessage(err, 'Unable to load normalized job profile'))
    })
    return () => { active = false }
  }, [state.jdDocumentId, state.jdNormalized])

  /**
   * Poll GET /projects/{projectId}/job-description until parse finishes or fails.
   * Uses document.processing_status / processing_stage from the existing Document contract.
   */
  const pollUntilParsed = async (documentId: string) => {
    const started = Date.now()
    while (Date.now() - started < PARSE_POLL_TIMEOUT_MS) {
      const doc = await api.getDocument(documentId)
      updateJdProcessing({
        status: doc.processing_status,
        stage: doc.processing_stage,
      })

      if (doc.processing_status === 'FAILED' || doc.processing_stage === 'FAILED') {
        throw new Error('JD parsing failed')
      }

      if (isParseTerminalSuccess(doc.processing_status)) {
        return doc
      }

      await sleep(PARSE_POLL_INTERVAL_MS)
    }
    throw new Error('Timed out waiting for JD parsing to complete')
  }

  const processUploadedJd = async (projectId: string, documentId: string) => {
    dispatch({ type: 'SET_PROCESSING', payload: true })
    updateJdProcessing({ normalized: false })

    try {
      setFlowPhase('parsing')
      const parseResult = await api.parseDocument(documentId)
      updateJdProcessing({
        status: parseResult.processing_status,
        stage: parseResult.processing_stage,
      })

      if (!isParseTerminalSuccess(parseResult.processing_status)) {
        await pollUntilParsed(documentId)
      }

      const parsedData = await api.getParsedDocument(documentId)
      console.log(`[Phase 1] JD Parsed successfully. Raw text length: ${parsedData.raw_text.length}`)
      
      // Real extraction call
      setFlowPhase('extracting')
      updateJdProcessing({ stage: 'EXTRACTION', status: 'IN_PROGRESS' })
      const extractResult = await api.extractDocument(documentId)
      updateJdProcessing({
        status: extractResult.processing_status,
        stage: extractResult.processing_stage,
      })

      // Real normalization call
      setFlowPhase('normalizing')
      updateJdProcessing({ stage: 'NORMALIZATION', status: 'IN_PROGRESS' })
      const normalizeResult = await api.normalizeDocument(documentId)
      updateJdProcessing({
        status: normalizeResult.processing_status,
        stage: normalizeResult.processing_stage,
        normalized: true,
      })

      setFlowPhase('ready')
    } catch (err) {
      setFlowPhase('error')
      setFlowError(errorMessage(err, 'JD processing failed'))
      updateJdProcessing({ status: 'FAILED', stage: 'FAILED' })
    } finally {
      dispatch({ type: 'SET_PROCESSING', payload: false })
    }
  }

  const handleJDSelect = async (files: File[]) => {
    const file = files[0]
    if (!file || busy) return

    if (!state.projectId) {
      setFlowError('Open or create a project before uploading a job description.')
      return
    }

    setFlowError(null)
    setFlowPhase('uploading')
    updateJdProcessing({
      status: null,
      stage: null,
      normalized: false,
    })

    const localPreview: UploadedFile = {
      id: `pending-${Date.now()}`,
      name: file.name,
      size: file.size,
      type: fileTypeFromName(file.name),
      status: 'uploading',
    }
    dispatch({ type: 'SET_JD', payload: localPreview })
    dispatch({ type: 'SET_JD_DOCUMENT_ID', payload: null })

    let uploadedFile: UploadedFile | null = null

    try {
      const projectId = state.projectId

      const uploaded = await api.uploadJobDescription(projectId, file)

      uploadedFile = {
        id: uploaded.document_id,
        name: uploaded.filename,
        size: file.size,
        type: fileTypeFromName(uploaded.filename),
        status: 'done',
        uploadedAt: new Date(),
      }

      dispatch({ type: 'SET_JD_DOCUMENT_ID', payload: uploaded.document_id })
      updateJdProcessing({
        status: uploaded.processing_status,
        stage: uploaded.processing_stage,
        normalized: false,
      })
      dispatch({ type: 'SET_JD', payload: uploadedFile })

      await processUploadedJd(projectId, uploaded.document_id)
    } catch (err) {
      const isDuplicate = err instanceof ApiError &&
        (err.status === 409 || err.code === 'DUPLICATE_DOCUMENT')
      const message = isDuplicate
        ? 'This job description already exists in the current project. Continue this screening or start a New Screening to use it in a new project.'
        : errorMessage(err, 'JD upload / processing failed')
      setFlowError(message)
      setFlowPhase('error')
      updateJdProcessing({
        status: isDuplicate ? null : 'FAILED',
        stage: isDuplicate ? null : 'FAILED',
        normalized: false,
      })
      dispatch({
        type: 'SET_JD',
        payload: {
          ...(uploadedFile ?? localPreview),
          status: 'error',
          errorMessage: message,
        },
      })
      dispatch({ type: 'SET_PROCESSING', payload: false })
    }
  }

  const handleRemoveJD = () => {
    if (busy) return
    setFlowError(null)
    setFlowPhase('idle')
    dispatch({ type: 'SET_JD', payload: null })
    dispatch({ type: 'SET_JD_DOCUMENT_ID', payload: null })
    updateJdProcessing({ status: null, stage: null, normalized: false })
  }

  const handleContinue = () => {
    if (!canProceedJD) return
    completeAndAdvance()
    navigate(`/projects/${state.projectId}/resumes`)
  }

  const jdCount = state.jdNormalized && state.jdDocumentId ? 1 : 0
  const statusText = processingLabel(
    state.jdProcessingStage,
    state.jdProcessingStatus,
    state.jdNormalized,
    busy,
  )

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="max-w-5xl mx-auto"
    >
      {/* Page Header */}
      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[30px] font-bold tracking-tight text-slate-900 mb-2">Job Description</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          Define the role you're hiring for. Upload a PDF, DOCX, or TXT document to begin processing.
        </p>
      </motion.div>

      {/* Info Strip */}
      <motion.div
        variants={fadeUp}
        className="card glow-border-sky mb-5 p-0 overflow-hidden"
      >
        <div className="flex divide-x divide-slate-100">
          {/* Supported Formats */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              Supported Formats
            </p>
            <div className="flex items-center gap-3">
              {[
                { icon: '📄', label: 'PDF', color: 'text-red-500' },
                { icon: '📝', label: 'DOCX', color: 'text-sky-500' },
                { icon: '📃', label: 'TXT', color: 'text-slate-400' },
              ].map((fmt) => (
                <motion.div
                  key={fmt.label}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-100"
                  whileHover={{ scale: 1.04 }}
                >
                  <span className="text-[13px]">{fmt.icon}</span>
                  <span className={`text-[12px] font-bold ${fmt.color}`}>{fmt.label}</span>
                </motion.div>
              ))}
            </div>
          </div>

          {/* File Limit */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              File Limit
            </p>
            <div className="flex items-center gap-2">
              <FileCheck size={16} className="text-sky-400" />
              <span className="text-[13px] font-semibold text-slate-700">
                Max 10 MB per file
              </span>
            </div>
          </div>

          {/* Security */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              Security
            </p>
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-sky-400" />
              <span className="text-[13px] font-semibold text-slate-700">
                Files are encrypted and secure
              </span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Upload Card (Job Description Only) */}
      <motion.div variants={fadeUp} className="mb-5">
        <UploadCard
          title="Job Description"
          subtitle="Upload the job description (JD) file"
          icon={<FileText size={28} />}
          color="blue"
          multiple={false}
          files={state.upload.jobDescription ? [state.upload.jobDescription] : []}
          onSelectFiles={handleJDSelect}
          onRemove={handleRemoveJD}
          disabled={busy}
        />
        {busy && (
          <p className="mt-2 text-[12px] text-sky-600 text-center font-medium">{statusText}</p>
        )}
        {flowError && (
          <p className="mt-2 text-[12px] text-red-500 text-center">{flowError}</p>
        )}
        {state.jdNormalized && !busy && !flowError && (
          <p className="mt-2 text-[12px] text-green-600 text-center font-medium">
            Job description parsed, extracted, and normalized successfully.
          </p>
        )}
      </motion.div>

      {state.jdNormalized && !profile && !profileError && <div className="card mb-5 p-6 text-[12px] text-slate-500">Loading final job profile…</div>}
      {profileError && <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-[12px] text-red-700">Normalization failed: {profileError}</div>}
      {profile && <div className="mb-5"><JobProfile {...profile}/></div>}

      {/* Bottom Row */}
      <motion.div variants={fadeUp} className="card glow-border-sky p-0 overflow-hidden">
        <div className="flex divide-x divide-slate-100">
          {/* Total Files */}
          <div className="p-5 min-w-[160px]">
            <div className="flex items-center gap-2 mb-2">
              <FileText size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                JD Uploaded
              </p>
            </div>
            <motion.p
              key={jdCount}
              className="text-[32px] font-bold text-slate-800 leading-none"
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 300 }}
            >
              {jdCount}
            </motion.p>
            <p className="text-[11px] text-slate-400 mt-1">
              {jdCount === 0
                ? busy
                  ? statusText
                  : flowPhase === 'error'
                    ? 'Processing failed'
                    : 'No JD uploaded yet'
                : 'Job Description ready'}
            </p>
          </div>

          {/* Tips */}
          <div className="flex-1 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Lightbulb size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                Upload Tips
              </p>
            </div>
            <ul className="space-y-1.5">
              {[
                'Ensure the JD file is clear and readable.',
                'Include key role requirements, qualifications, and responsibilities.',
                'Supported languages: English only.',
              ].map((tip, i) => (
                <motion.li
                  key={i}
                  className="flex items-start gap-2 text-[12px] text-slate-500"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.4 + i * 0.07 }}
                >
                  <Check size={13} className="text-sky-400 flex-shrink-0 mt-0.5" />
                  {tip}
                </motion.li>
              ))}
            </ul>
          </div>

          {/* CTA */}
          <div className="flex flex-col items-center justify-center p-6 min-w-[220px]">
            <motion.button
              className="btn-primary w-full justify-center text-[13px] py-3 mb-2"
              onClick={handleContinue}
              disabled={!canProceedJD}
              whileHover={canProceedJD ? { scale: 1.02 } : undefined}
              whileTap={canProceedJD ? { scale: 0.98 } : undefined}
              animate={canProceedJD ? { boxShadow: ['0 4px 12px rgba(2,132,199,0.3)', '0 6px 20px rgba(2,132,199,0.5)', '0 4px 12px rgba(2,132,199,0.3)'] } : undefined}
              transition={canProceedJD ? { duration: 2, repeat: Infinity } : undefined}
            >
              Continue to Resume Upload              <ArrowRight size={15} />
            </motion.button>
            <p className="text-[10px] text-slate-400 text-center leading-relaxed">
              You can only proceed when<br />
              the JD is normalized.
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}
