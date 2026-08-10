import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Folder,
  Shield,
  Lightbulb,
  Check,
  ArrowLeft,
  ArrowRight,
  FileCheck,
  Users,
} from 'lucide-react'
import UploadCard from '@/components/ui/UploadCard'
import { usePipeline } from '@/store/pipelineStore'
import {
  UploadedFile,
  DocumentProcessingStatus,
  ResumeProcessingState,
} from '@/types'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/api'

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

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

function isParseTerminalSuccess(status: DocumentProcessingStatus): boolean {
  // Backend parse_document sets COMPLETED (not PARSED) on success.
  return status === 'COMPLETED' || status === 'PARSED'
}

export default function ResumeUpload() {
  const { state, dispatch, canProceedResumes, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()
  const [isUploading, setIsUploading] = useState(false)
  const [isProcessingResumes, setIsProcessingResumes] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const processingRef = useRef<Set<string>>(new Set())

  const successfulCount = state.resumeDocumentIds.length
  const normalizedCount = state.resumeDocumentIds.filter(
    (id) => state.resumeProcessing[id]?.normalized,
  ).length
  const failedCount = state.upload.resumes.filter((r) => r.status === 'error').length
  const busy = isUploading || isProcessingResumes

  const upsertProcessing = useCallback(
    (payload: ResumeProcessingState) => {
      dispatch({ type: 'UPSERT_RESUME_PROCESSING', payload })
    },
    [dispatch],
  )

  const patchResumeFile = useCallback(
    (id: string, patch: Partial<UploadedFile>) => {
      dispatch({ type: 'UPDATE_RESUME', payload: { id, patch } })
    },
    [dispatch],
  )

  /**
   * Poll GET /documents/{documentId} until parse finishes or fails.
   */
  const pollUntilParsed = useCallback(
    async (documentId: string) => {
      const started = Date.now()
      while (Date.now() - started < PARSE_POLL_TIMEOUT_MS) {
        const doc = await api.getDocument(documentId)
        upsertProcessing({
          documentId,
          phase: 'parsing',
          status: doc.processing_status,
          stage: doc.processing_stage,
          normalized: false,
        })

        if (doc.processing_status === 'FAILED' || doc.processing_stage === 'FAILED') {
          throw new Error('Resume parsing failed')
        }

        if (isParseTerminalSuccess(doc.processing_status)) {
          return doc
        }

        await sleep(PARSE_POLL_INTERVAL_MS)
      }
      throw new Error('Timed out waiting for resume parsing to complete')
    },
    [upsertProcessing],
  )

  const processOneResume = useCallback(
    async (documentId: string) => {
      if (processingRef.current.has(documentId)) return
      processingRef.current.add(documentId)

      try {
        patchResumeFile(documentId, {
          status: 'processing',
          statusLabel: 'Parsing…',
          errorMessage: undefined,
        })
        upsertProcessing({
          documentId,
          phase: 'parsing',
          status: 'IN_PROGRESS',
          stage: 'PARSING',
          normalized: false,
        })

        const parseResult = await api.parseDocument(documentId)
        upsertProcessing({
          documentId,
          phase: 'parsing',
          status: parseResult.processing_status,
          stage: parseResult.processing_stage,
          normalized: false,
        })

        if (!isParseTerminalSuccess(parseResult.processing_status)) {
          await pollUntilParsed(documentId)
        }

        patchResumeFile(documentId, {
          status: 'processing',
          statusLabel: 'Extracting…',
        })
        upsertProcessing({
          documentId,
          phase: 'extracting',
          status: 'IN_PROGRESS',
          stage: 'EXTRACTION',
          normalized: false,
        })
        const extractResult = await api.extractDocument(documentId)
        upsertProcessing({
          documentId,
          phase: 'extracting',
          status: 'COMPLETED',
          stage: extractResult.processing_stage,
          normalized: false,
        })

        patchResumeFile(documentId, {
          status: 'processing',
          statusLabel: 'Normalizing…',
        })
        upsertProcessing({
          documentId,
          phase: 'normalizing',
          status: 'IN_PROGRESS',
          stage: 'NORMALIZATION',
          normalized: false,
        })
        const normalizeResult = await api.normalizeDocument(documentId)
        upsertProcessing({
          documentId,
          phase: 'normalized',
          status: 'COMPLETED',
          stage: normalizeResult.processing_stage,
          normalized: true,
        })
        patchResumeFile(documentId, {
          status: 'done',
          statusLabel: undefined,
          errorMessage: undefined,
        })
      } catch (err) {
        const message = errorMessage(err, 'Resume processing failed')
        upsertProcessing({
          documentId,
          phase: 'failed',
          status: 'FAILED',
          stage: 'FAILED',
          normalized: false,
          errorMessage: message,
        })
        patchResumeFile(documentId, {
          status: 'error',
          statusLabel: undefined,
          errorMessage: message,
        })
      } finally {
        processingRef.current.delete(documentId)
      }
    },
    [patchResumeFile, pollUntilParsed, upsertProcessing],
  )

  const processResumes = useCallback(
    async (documentIds: string[]) => {
      const ids = documentIds.filter((id) => {
        const current = state.resumeProcessing[id]
        if (current?.normalized) return false
        if (current?.phase === 'failed') return false
        if (processingRef.current.has(id)) return false
        return true
      })
      if (ids.length === 0) return

      setIsProcessingResumes(true)
      try {
        await Promise.allSettled(ids.map((id) => processOneResume(id)))
      } finally {
        setIsProcessingResumes(false)
      }
    },
    [processOneResume, state.resumeProcessing],
  )

  // Resume incomplete processing for already-uploaded document IDs (e.g. after refresh mid-flow).
  useEffect(() => {
    const pending = state.resumeDocumentIds.filter((id) => {
      const p = state.resumeProcessing[id]
      return p && !p.normalized && p.phase === 'uploaded'
    })
    if (pending.length > 0) {
      void processResumes(pending)
    }
    // Run once on mount for leftover uploaded-but-unprocessed resumes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleResumeSelect = async (files: File[]) => {
    if (files.length === 0 || busy) return

    const projectId = state.projectId
    if (!projectId) {
      setUploadError('No project found. Complete JD upload and weightage first.')
      return
    }

    setUploadError(null)
    setIsUploading(true)

    const pending: UploadedFile[] = files.map((file, index) => ({
      id: `pending-resume-${Date.now()}-${index}`,
      name: file.name,
      size: file.size,
      type: fileTypeFromName(file.name),
      status: 'uploading',
    }))
    dispatch({ type: 'ADD_RESUMES', payload: pending })

    const sizeByName = new Map(files.map((f) => [f.name, f.size]))
    let uploadedIds: string[] = []

    try {
      // POST /projects/{id}/resumes/batch — multipart field name: "files"
      // Backend returns HTTP 207 with successful_uploads + failed_uploads.
      const batch = await api.uploadResumeBatch(projectId, files)

      for (const item of pending) {
        dispatch({ type: 'REMOVE_RESUME', payload: item.id })
      }

      const successes: UploadedFile[] = batch.successful_uploads.map((upload: any) => ({
        id: upload.document_id,
        name: upload.filename,
        size: sizeByName.get(upload.filename) ?? 0,
        type: fileTypeFromName(upload.filename),
        status: 'done',
        uploadedAt: new Date(),
      }))

      const failures: UploadedFile[] = batch.failed_uploads.map((failed: any, index: number) => ({
        id: `failed-resume-${Date.now()}-${index}`,
        name: failed.original_filename,
        size: sizeByName.get(failed.original_filename) ?? 0,
        type: fileTypeFromName(failed.original_filename),
        status: 'error',
        errorMessage: failed.message || failed.error_code,
      }))

      if (successes.length > 0 || failures.length > 0) {
        dispatch({ type: 'ADD_RESUMES', payload: [...successes, ...failures] })
      }

      uploadedIds = successes.map((s) => s.id)

      if (batch.successful_count === 0 && batch.failed_count > 0) {
        setUploadError('All resumes failed to upload. Check file format and size limits.')
      }
    } catch (err) {
      for (const item of pending) {
        dispatch({ type: 'REMOVE_RESUME', payload: item.id })
      }

      const failures: UploadedFile[] = files.map((file, index) => ({
        id: `failed-resume-${Date.now()}-${index}`,
        name: file.name,
        size: file.size,
        type: fileTypeFromName(file.name),
        status: 'error',
        errorMessage:
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Upload failed',
      }))
      dispatch({ type: 'ADD_RESUMES', payload: failures })

      setUploadError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Resume batch upload failed',
      )
    } finally {
      setIsUploading(false)
    }

    if (uploadedIds.length > 0) {
      await processResumes(uploadedIds)
    }
  }

  const handleRemoveResume = (id: string) =>
    dispatch({ type: 'REMOVE_RESUME', payload: id })

  const handleContinue = () => {
    if (!canProceedResumes) return
    completeAndAdvance()
    navigate('/ranking')
  }

  const handleBack = () => {
    navigate('/weightage')
  }

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="max-w-5xl mx-auto"
    >
      {/* Page Header */}
      <motion.div variants={fadeUp} className="mb-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold text-slate-800 mb-1">Resume Upload</h1>
          <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
            Upload candidate <strong className="text-slate-600">resumes or resume folders</strong>.
            All documents are automatically extracted, standardized, and scored against your weighted criteria.
          </p>
        </div>
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
                Max 10 MB per resume
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

      {/* Upload Card (Resume Folder Only) */}
      <motion.div variants={fadeUp} className="mb-5">
        <UploadCard
          title="Resume Folder"
          subtitle="Upload candidate resumes or a folder of resumes"
          icon={<Folder size={28} />}
          color="red"
          multiple={true}
          files={state.upload.resumes}
          onSelectFiles={handleResumeSelect}
          onRemove={handleRemoveResume}
          disabled={busy}
        />
        {isUploading && (
          <p className="mt-2 text-[12px] text-sky-600 text-center font-medium">
            Uploading resumes…
          </p>
        )}
        {isProcessingResumes && !isUploading && (
          <p className="mt-2 text-[12px] text-sky-600 text-center font-medium">
            Processing resumes (parse → extract → normalize)…
          </p>
        )}
        {uploadError && (
          <p className="mt-2 text-[12px] text-red-500 text-center">{uploadError}</p>
        )}
      </motion.div>

      {/* Bottom Summary Strip & Action Footer */}
      <motion.div variants={fadeUp} className="card glow-border-sky p-0 overflow-hidden mb-5">
        <div className="flex divide-x divide-slate-100">
          {/* Total Resumes */}
          <div className="p-5 min-w-[180px]">
            <div className="flex items-center gap-2 mb-2">
              <Users size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                Resumes Queued
              </p>
            </div>
            <motion.p
              key={`${successfulCount}-${normalizedCount}`}
              className="text-[32px] font-bold text-slate-800 leading-none"
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 300 }}
            >
              {successfulCount}
            </motion.p>
            <p className="text-[11px] text-slate-400 mt-1">
              {successfulCount === 0
                ? busy
                  ? 'Upload in progress…'
                  : 'No resumes uploaded yet'
                : `${normalizedCount}/${successfulCount} normalized`}
              {failedCount > 0 ? ` · ${failedCount} failed` : ''}
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
                'Ensure candidate resumes are clearly formatted and text-searchable.',
                'Multiple files or whole folders can be selected at once.',
                'System automatically removes duplicates and standardizes fields.',
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
        </div>
      </motion.div>

      {/* Action Footer Bar */}
      <motion.div variants={fadeUp} className="card p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
            PIPELINE PROGRESS
          </p>
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-slate-200" />
            <div className="w-6 h-2 rounded-full bg-slate-200" />
          </div>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <motion.button
            onClick={handleBack}
            disabled={busy}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="btn-outline flex-1 sm:flex-initial py-2.5 px-5 text-[13px] flex items-center justify-center gap-2 font-medium"
          >
            <ArrowLeft size={15} />
            Back to Weightage
          </motion.button>

          <motion.button
            onClick={handleContinue}
            disabled={!canProceedResumes || busy}
            whileHover={canProceedResumes && !busy ? { scale: 1.02 } : undefined}
            whileTap={canProceedResumes && !busy ? { scale: 0.98 } : undefined}
            className={`flex-1 sm:flex-initial py-2.5 px-6 rounded-xl text-[13px] font-semibold flex items-center justify-center gap-2 transition-all shadow-sky-sm ${
              canProceedResumes && !busy
                ? 'bg-sky-600 hover:bg-sky-700 text-white cursor-pointer'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed border-transparent shadow-none'
            }`}
          >
            Continue to Candidate Ranking
            <ArrowRight size={15} />
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}
