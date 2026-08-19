import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Folder,
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
import type { Document as ApiDocument, ExtractedResume, NormalizedResume } from '@/api'
import { CandidateProfile } from '@/components/ui/DocumentProfiles'

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
const SUPPORTED_RESUME_EXTENSIONS = new Set(['pdf', 'docx', 'txt'])

function fileTypeFromName(name: string): UploadedFile['type'] {
  const ext = name.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx') return 'docx'
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
  const [listError, setListError] = useState<string | null>(null)
  const processingRef = useRef<Set<string>>(new Set())
  const [profiles, setProfiles] = useState<Record<string, { normalized?: NormalizedResume; extracted?: ExtractedResume | null; document?: ApiDocument; error?: string; loading?: boolean }>>({})

  const successfulCount = state.resumeDocumentIds.length
  const normalizedCount = state.resumeDocumentIds.filter(
    (id) => state.resumeProcessing[id]?.normalized,
  ).length
  const failedCount = state.upload.resumes.filter((r: UploadedFile) => r.status === 'error').length
  const busy = isUploading || isProcessingResumes

  const refreshResumes = useCallback(async () => {
    if (!state.projectId) return
    try {
      const result = await api.listProjectResumes(state.projectId)
      const resumes: UploadedFile[] = result.items.map((document) => ({
        id: document.id,
        name: document.original_filename,
        size: document.file_size_bytes,
        type: fileTypeFromName(document.original_filename),
        status: document.processing_status === 'FAILED' ? 'error' : 'done',
        statusLabel: document.processing_status,
        errorMessage: document.error_message ?? undefined,
        uploadedAt: new Date(document.created_at),
      }))
      dispatch({ type: 'SET_RESUMES', payload: resumes })
      setListError(null)
    } catch (err) {
      setListError(`Resume listing failed: ${errorMessage(err, 'Unknown error')}`)
    }
  }, [dispatch, state.projectId])

  useEffect(() => {
    if (state.projectId) void refreshResumes()
  }, [refreshResumes, state.projectId])

  useEffect(() => {
    const normalizedIds = state.resumeDocumentIds.filter((id) => state.resumeProcessing[id]?.normalized)
    if (!normalizedIds.length) return
    const idsToFetch = normalizedIds.filter((id) => !profiles[id]?.normalized && !profiles[id]?.error)
    if (!idsToFetch.length) return
    let active = true
    setProfiles((current) => {
      const next = { ...current }
      idsToFetch.forEach((id) => { next[id] = { ...next[id], loading: true, error: undefined } })
      return next
    })
    Promise.all(idsToFetch.map(async (id) => {
      try {
        const [normalized, extracted, document] = await Promise.all([api.getNormalizedDocument(id), api.getExtractedDocument(id).catch(() => null), api.getDocument(id)])
        if ('job_titles' in normalized) return [id, { normalized, extracted: extracted && 'candidate_name' in extracted ? extracted : null, document, loading: false }] as const
        return [id, { error: 'Normalized resume data was not returned.', loading: false }] as const
      } catch (err) {
        return [id, { error: errorMessage(err, 'Unable to load normalized candidate profile'), loading: false }] as const
      }
    })).then((entries) => { if (active) setProfiles((current) => ({ ...current, ...Object.fromEntries(entries) })) })
    return () => { active = false }
  }, [normalizedCount, state.resumeDocumentIds, state.resumeProcessing, profiles])


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

        // Fetch candidate profile data immediately to avoid trailing loading delay
        try {
          const [normalized, extracted, document] = await Promise.all([
            api.getNormalizedDocument(documentId),
            api.getExtractedDocument(documentId).catch(() => null),
            api.getDocument(documentId),
          ])
          if ('job_titles' in normalized) {
            setProfiles((current) => ({
              ...current,
              [documentId]: {
                normalized,
                extracted: extracted && 'candidate_name' in extracted ? extracted : null,
                document,
                loading: false,
              },
            }))
          }
        } catch {
          // Failure handling will fallback to useEffect if needed
        }

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

    const supported = files.filter((file) =>
      SUPPORTED_RESUME_EXTENSIONS.has(file.name.split('.').pop()?.toLowerCase() ?? ''),
    )
    const unsupported = files.filter((file) => !supported.includes(file))
    if (supported.length === 0) {
      setUploadError(
        files.length === 0
          ? 'The selected folder is empty.'
          : 'No supported resumes found. Select PDF, DOCX, or TXT files.',
      )
      return
    }
    if (unsupported.length > 0) {
      setUploadError(
        `${unsupported.length} unsupported file${unsupported.length === 1 ? '' : 's'} skipped. Only PDF, DOCX, and TXT are supported.`,
      )
    }

    const projectId = state.projectId
    if (!projectId) {
      setUploadError('No project found. Complete JD upload and weightage first.')
      return
    }

    if (unsupported.length === 0) setUploadError(null)
    setIsUploading(true)

    files = supported
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
        const detail = batch.failed_uploads.map((failure) => failure.message).join('; ')
        setUploadError(`Upload failed: ${detail || 'Check file format and size limits.'}`)
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
    await refreshResumes()
  }

  const handleRemoveResume = (id: string) =>
    dispatch({ type: 'REMOVE_RESUME', payload: id })

  const [isScoringAndRanking, setIsScoringAndRanking] = useState(false)

  const handleContinue = async () => {
    if (!canProceedResumes || !state.projectId || busy || isScoringAndRanking) return
    try {
      setIsScoringAndRanking(true)
      setUploadError(null)
      // 1. Score candidates via existing backend endpoint
      await api.scoreProject(state.projectId)
      // 2. Rank candidates via existing backend endpoint
      await api.rankProject(state.projectId)
      completeAndAdvance()
      navigate(`/projects/${state.projectId}/rankings`)
    } catch (err) {
      setUploadError(errorMessage(err, 'Failed to score and rank candidates'))
    } finally {
      setIsScoringAndRanking(false)
    }
  }

  const handleBack = () => {
    navigate(`/projects/${state.projectId}/job-description`)
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
          <h1 className="text-[30px] font-bold tracking-tight text-slate-900 mb-2">Candidate Resumes</h1>
          <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
            Upload and process resumes for this project. Each candidate remains isolated to the active project.
          </p>
        </div>
      </motion.div>

      {/* Info Strip */}
      <motion.div
        variants={fadeUp}
        className="card glow-border-sky mb-5 p-0 overflow-hidden"
      >
        <div className="flex flex-col sm:flex-row divide-y sm:divide-y-0 sm:divide-x divide-slate-100">
          {/* Supported Formats */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              Supported Formats
            </p>
            <div className="flex items-center gap-2">
              {['PDF', 'DOCX', 'TXT'].map((fmt) => (
                <div
                  key={fmt}
                  className="px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200/80 text-[12px] font-semibold text-slate-700"
                >
                  {fmt}
                </div>
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
        </div>
      </motion.div>

      {/* Upload Card (Resume Folder Only) */}
      <motion.div variants={fadeUp} className="mb-5">
        <UploadCard
          title="Resume Folder"
          subtitle="Upload candidate resumes or a folder of resumes"
          icon={<Folder size={28} />}
          color="red"
          accept=".pdf,.docx,.txt"
          multiple={true}
          directory={true}
          files={state.upload.resumes}
          resumeProcessing={state.resumeProcessing}
          onSelectFiles={handleResumeSelect}
          onRemove={handleRemoveResume}
          disabled={busy}
        />
        {isUploading && (
          <p className="mt-2 text-[12px] text-sky-600 text-center font-medium">
            Uploading resumes…
          </p>
        )}
        {uploadError && (
          <p className="mt-2 text-[12px] text-red-500 text-center">{uploadError}</p>
        )}
        {listError && (
          <p className="mt-2 text-[12px] text-red-500 text-center">{listError}</p>
        )}
      </motion.div>

      {/* Processed Candidate Profiles (only when ready) */}
      {state.resumeDocumentIds.some((id) => state.resumeProcessing[id]?.normalized) && (
        <motion.section variants={fadeUp} className="mb-5 space-y-4">
          <div>
            <h2 className="text-[18px] font-bold text-slate-900">Processed candidate profiles</h2>
            <p className="mt-1 text-[12px] text-slate-500">
              Each profile is loaded from its document’s backend extraction and normalization records.
            </p>
          </div>
          {state.resumeDocumentIds.map((id) => {
            const processing = state.resumeProcessing[id]
            const profile = profiles[id]
            if (!processing?.normalized) return null
            return (
              <article key={id} className="space-y-3">
                {profile?.loading && (
                  <div className="card p-6 text-[12px] text-slate-500">Loading final candidate profile…</div>
                )}
                {profile?.error && (
                  <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-700">{profile.error}</p>
                )}
                {profile?.normalized && (
                  <CandidateProfile
                    normalized={profile.normalized}
                    extracted={profile.extracted}
                    document={profile.document}
                  />
                )}
              </article>
            )
          })}
        </motion.section>
      )}

      {/* Resumes Queued Status Card (Upload Tips removed) */}
      <motion.div variants={fadeUp} className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs mb-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50/80 text-blue-600 flex items-center justify-center shrink-0 shadow-xs border border-blue-100/60">
              <Users size={22} />
            </div>
            <div>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Resumes Queued</p>
              <div className="flex items-baseline gap-2 mt-0.5">
                <motion.p
                  key={`${successfulCount}-${normalizedCount}`}
                  className="text-2.5xl font-extrabold text-slate-900 leading-none"
                  initial={{ scale: 0.8, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: 'spring', stiffness: 300 }}
                >
                  {successfulCount}
                </motion.p>
                <span className="text-xs text-slate-400 font-medium">candidates</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <div className="px-3.5 py-2 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center gap-2">
              <span className="text-[11px] font-semibold text-slate-500">Normalized:</span>
              <span className="text-xs font-bold text-emerald-600">
                {normalizedCount} / {successfulCount}
              </span>
            </div>
            {failedCount > 0 && (
              <div className="px-3.5 py-2 rounded-xl bg-red-50 border border-red-200/80 flex items-center gap-2">
                <span className="text-[11px] font-semibold text-red-600">Failed:</span>
                <span className="text-xs font-bold text-red-700">{failedCount}</span>
              </div>
            )}
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
            Back to Job Description
          </motion.button>

          <motion.button
            onClick={() => void handleContinue()}
            disabled={!canProceedResumes || busy || isScoringAndRanking}
            whileHover={canProceedResumes && !busy && !isScoringAndRanking ? { scale: 1.02 } : undefined}
            whileTap={canProceedResumes && !busy && !isScoringAndRanking ? { scale: 0.98 } : undefined}
            className={`flex-1 sm:flex-initial py-2.5 px-6 rounded-xl text-[13px] font-semibold flex items-center justify-center gap-2 transition-all shadow-sky-sm ${
              canProceedResumes && !busy && !isScoringAndRanking
                ? 'bg-sky-600 hover:bg-sky-700 text-white cursor-pointer'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed border-transparent shadow-none'
            }`}
          >
            {isScoringAndRanking ? 'Scoring & Ranking Candidate Resumes…' : 'Continue to Candidate Ranking'}
            <ArrowRight size={15} />
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}
