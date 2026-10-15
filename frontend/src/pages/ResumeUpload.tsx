import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Folder,
  ArrowLeft,
  ArrowRight,
  FileCheck,
  Users,
  Loader2,
  Sparkles,
  Briefcase,
  AlertCircle,
  CheckCircle2,
  Mail,
  Phone,
  Search,
  FileText,
  ShieldCheck,
  Database,
  Cpu,
  Trash2,
} from 'lucide-react'
import UploadCard from '@/components/ui/UploadCard'
import { usePipeline } from '@/store/pipelineStore'
import {
  UploadedFile,
  DocumentProcessingStatus,
  ResumeProcessingState,
} from '@/types'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, ZohoJobOpening } from '@/api'
import type { Document as ApiDocument, ExtractedResume, NormalizedResume } from '@/api'
import { CandidateProfile } from '@/components/ui/DocumentProfiles'
import ZohoImportModal from '@/components/ui/ZohoImportModal'

interface ProcessingPipelineState {
  jobTitle: string
  jobCode?: string
  status: 'running' | 'completed' | 'failed'
  currentStepIndex: number
  totalFound?: number
  alreadyFetched?: number
  newResumes?: number
  currentDocIndex?: number
  totalDocs?: number
  statusMessage: string
  errorMessage?: string
}

const PIPELINE_STEPS = [
  {
    id: 1,
    title: 'Zoho Ingestion & Deduplication',
    shortDesc: 'Sync candidate attachments & verify idempotency',
    icon: Database,
  },
  {
    id: 2,
    title: 'Document Parsing',
    shortDesc: 'Convert PDF / DOCX resumes to raw text',
    icon: FileText,
  },
  {
    id: 3,
    title: 'Data Extraction',
    shortDesc: 'Extract candidate identity, skills & history',
    icon: Cpu,
  },
  {
    id: 4,
    title: 'Profile Normalization',
    shortDesc: 'Standardize profiles & prepare for screening',
    icon: ShieldCheck,
  },
] as const

function getStepStatus(
  stepId: number,
  state: ProcessingPipelineState,
): 'pending' | 'in_progress' | 'completed' | 'skipped' {
  if (state.status === 'completed' && state.newResumes === 0 && stepId > 1) {
    return 'skipped'
  }
  if (state.status === 'completed') {
    return 'completed'
  }
  if (state.currentStepIndex === stepId && state.status === 'running') {
    return 'in_progress'
  }
  if (state.currentStepIndex > stepId) {
    return 'completed'
  }
  return 'pending'
}

function calculateProgressPercent(pipeline: ProcessingPipelineState): number {
  if (pipeline.status === 'completed') return 100
  if (pipeline.status === 'failed') return 100
  if (pipeline.currentStepIndex === 1) return 20
  const docsRatio =
    pipeline.totalDocs && pipeline.totalDocs > 0
      ? Math.min(1, ((pipeline.currentDocIndex ?? 1) - 0.2) / pipeline.totalDocs)
      : 0.5
  if (pipeline.currentStepIndex === 2) return Math.round(25 + 25 * docsRatio)
  if (pipeline.currentStepIndex === 3) return Math.round(50 + 25 * docsRatio)
  if (pipeline.currentStepIndex === 4) return Math.round(75 + 20 * docsRatio)
  return 10
}

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

function getCandidateDisplayName(doc: ApiDocument): string {
  const meta = doc.metadata_json || {}
  if (meta.candidate_name && typeof meta.candidate_name === 'string' && meta.candidate_name.trim()) {
    return meta.candidate_name.trim()
  }
  let cleanName = doc.original_filename.replace(/^[0-9]+_/, '').replace(/\.(pdf|docx|txt)$/i, '')
  cleanName = cleanName.replace(/^(SRE|Engineer|Senior|Lead|DevOps|Developer|Chennai|Bangalore|Coimbatore|Job)_+/gi, '')
  cleanName = cleanName.replace(/[_-]+/g, ' ').trim()
  return cleanName || doc.original_filename
}

function getInitials(name: string): string {
  const clean = name.replace(/[^A-Za-z\s]/g, '').trim()
  const parts = clean.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase()
  }
  return 'CD'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
  const [isZohoModalOpen, setIsZohoModalOpen] = useState(false)
  const [isZohoSyncing, setIsZohoSyncing] = useState(false)
  const [selectedZohoJobId, setSelectedZohoJobId] = useState<string | undefined>()
  const [zohoFeedback, setZohoFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const [zohoSummary, setZohoSummary] = useState<{
    jobOpeningTitle: string
    jobOpeningCode?: string
    jobId: string
    totalFound: number
    alreadyFetched: number
    newResumes: number
    failedResumes: number
  } | null>(null)
  const [pipelineState, setPipelineState] = useState<ProcessingPipelineState | null>(null)
  const [projectDocs, setProjectDocs] = useState<ApiDocument[]>([])
  const [newlyImportedIds, setNewlyImportedIds] = useState<Set<string>>(new Set())
  const processingRef = useRef<Set<string>>(new Set())
  const inFlightListRef = useRef<Promise<void> | null>(null)
  const [profiles, setProfiles] = useState<Record<string, { normalized?: NormalizedResume; extracted?: ExtractedResume | null; document?: ApiDocument; error?: string; loading?: boolean }>>({})

  const successfulCount = state.resumeDocumentIds.length
  const normalizedCount = state.resumeDocumentIds.filter(
    (id) => state.resumeProcessing[id]?.normalized,
  ).length
  const failedCount = state.upload.resumes.filter((r: UploadedFile) => r.status === 'error').length
  const [deletingResumeIds, setDeletingResumeIds] = useState<Set<string>>(new Set())
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [retryingResumeIds, setRetryingResumeIds] = useState<Set<string>>(new Set())
  const [retryFeedback, setRetryFeedback] = useState<{ id: string; type: 'success' | 'error'; message: string } | null>(null)
  const busy = isUploading || isProcessingResumes || isZohoSyncing || deletingResumeIds.size > 0 || retryingResumeIds.size > 0

  const refreshResumes = useCallback(async () => {
    if (!state.projectId) return
    if (inFlightListRef.current) return inFlightListRef.current
    const promise = (async () => {
      try {
        const result = await api.listProjectResumes(state.projectId!)
        setProjectDocs(result.items)
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
      } finally {
        inFlightListRef.current = null
      }
    })()
    inFlightListRef.current = promise
    return promise
  }, [dispatch, state.projectId])

  useEffect(() => {
    if (state.projectId) void refreshResumes()
  }, [refreshResumes, state.projectId])

  useEffect(() => {
    // Only fetch profiles for normalized documents that are not already present in profiles state
    const idsToFetch = state.resumeDocumentIds.filter(
      (id) => state.resumeProcessing[id]?.normalized && !profiles[id]?.normalized && !profiles[id]?.error
    )
    if (!idsToFetch.length) return
    let active = true

    Promise.all(
      idsToFetch.map(async (id) => {
        try {
          const [normalizedRes, extractedRes] = await Promise.all([
            api.getNormalizedDocument(id),
            api.getExtractedDocument(id).catch(() => null),
          ])
          const normalized = (normalizedRes && 'data' in normalizedRes) ? (normalizedRes as any).data : normalizedRes
          const extracted = (extractedRes && 'data' in extractedRes) ? (extractedRes as any).data : extractedRes

          if (normalized && typeof normalized === 'object' && 'job_titles' in normalized) {
            return [
              id,
              {
                normalized,
                extracted: extracted && typeof extracted === 'object' && 'candidate_name' in extracted ? extracted : null,
                loading: false,
              },
            ] as const
          }
          return null
        } catch {
          return null
        }
      })
    ).then((entries) => {
      if (active) {
        setProfiles((current) => {
          const next = { ...current }
          for (const entry of entries) {
            if (entry) {
              const [id, val] = entry
              // Never overwrite an existing normalized profile
              if (!next[id]?.normalized) {
                next[id] = val as any
              }
            }
          }
          return next
        })
      }
    })
    return () => {
      active = false
    }
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
    async (
      documentId: string,
      onStageChange?: (
        stage: 'parsing' | 'extracting' | 'normalizing' | 'done',
        docId: string,
      ) => void,
    ) => {
      if (processingRef.current.has(documentId)) return
      processingRef.current.add(documentId)

      try {
        onStageChange?.('parsing', documentId)
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

        onStageChange?.('extracting', documentId)
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

        onStageChange?.('normalizing', documentId)
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

        // Fetch complete candidate profile data directly after normalization completes
        try {
          const [normalized, extracted] = await Promise.all([
            api.getNormalizedDocument(documentId),
            api.getExtractedDocument(documentId).catch(() => null),
          ])
          setProfiles((current) => ({
            ...current,
            [documentId]: {
              normalized: normalized as any,
              extracted: extracted as any,
              loading: false,
              error: undefined,
            },
          }))
        } catch (err) {
          setProfiles((current) => ({
            ...current,
            [documentId]: {
              error: errorMessage(err, 'Unable to load candidate profile'),
              loading: false,
            },
          }))
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
        onStageChange?.('done', documentId)

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
    async (
      documentIds: string[],
      onDocStep?: (
        stage: 'parsing' | 'extracting' | 'normalizing' | 'done',
        docId: string,
        docIndex: number,
        total: number,
      ) => void,
    ) => {
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
        for (let i = 0; i < ids.length; i++) {
          const id = ids[i]
          await processOneResume(id, (stage, docId) => {
            onDocStep?.(stage, docId, i + 1, ids.length)
          })
        }
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

  const handleSelectZohoJob = async (job: ZohoJobOpening) => {
    if (!state.projectId || busy) return
    setIsZohoSyncing(true)
    setSelectedZohoJobId(job.id)
    setZohoFeedback(null)
    setUploadError(null)

    // Immediately close modal so it smoothly fades away via Framer Motion AnimatePresence
    setIsZohoModalOpen(false)

    // Initialize the processing pipeline state at Step 1: Ingestion & Deduplication
    setPipelineState({
      jobTitle: job.posting_title,
      jobCode: job.job_opening_id || undefined,
      status: 'running',
      currentStepIndex: 1,
      statusMessage: `Connecting to Zoho Recruit API & fetching candidate applicants for "${job.posting_title}"...`,
    })

    try {
      const res = await api.importZohoApplicants(state.projectId, job.id)
      const newlyIds = new Set((res.document_ids || []).map(String))
      setNewlyImportedIds(newlyIds)
      await refreshResumes()

      const totalFound = res.total_found ?? ((res.already_fetched ?? 0) + res.imported_count)
      const alreadyFetched = res.already_fetched ?? (res.total_resumes ? Math.max(0, res.total_resumes - res.imported_count) : 0)
      const newResumes = res.new_resumes ?? res.imported_count
      const failedResumes = res.failed_resumes ?? res.failed_count ?? 0

      setZohoSummary({
        jobOpeningTitle: job.posting_title,
        jobOpeningCode: job.job_opening_id || undefined,
        jobId: job.id,
        totalFound,
        alreadyFetched,
        newResumes,
        failedResumes,
      })

      if (newResumes === 0) {
        setPipelineState({
          jobTitle: job.posting_title,
          jobCode: job.job_opening_id || undefined,
          status: 'completed',
          currentStepIndex: 4,
          totalFound,
          alreadyFetched,
          newResumes: 0,
          statusMessage: `Idempotency verified: All ${alreadyFetched} candidate resumes were already imported and deduplicated.`,
        })
        setZohoFeedback({
          type: 'success',
          message: `Idempotency verified: All ${alreadyFetched} candidate resumes for this Job Opening were already imported and deduplicated.`,
        })
      } else {
        const totalDocs = res.document_ids?.length || newResumes
        setPipelineState({
          jobTitle: job.posting_title,
          jobCode: job.job_opening_id || undefined,
          status: 'running',
          currentStepIndex: 2,
          totalFound,
          alreadyFetched,
          newResumes,
          currentDocIndex: 1,
          totalDocs,
          statusMessage: `Imported ${newResumes} new resume(s). ${alreadyFetched} skipped. Step 2: Parsing resume text...`,
        })

        if (res.document_ids && res.document_ids.length > 0) {
          await processResumes(res.document_ids, (stage, _docId, docIndex, total) => {
            const stepIdx = stage === 'parsing' ? 2 : stage === 'extracting' ? 3 : stage === 'normalizing' ? 4 : 4
            const stageName =
              stage === 'parsing'
                ? 'Parsing resume text'
                : stage === 'extracting'
                  ? 'Extracting candidate entities & skills'
                  : 'Normalizing candidate profile'
            setPipelineState((prev) =>
              prev
                ? {
                    ...prev,
                    currentStepIndex: stepIdx,
                    currentDocIndex: docIndex,
                    totalDocs: total,
                    statusMessage: `Step ${stepIdx} of 4: ${stageName} (${docIndex} of ${total})...`,
                  }
                : null,
            )
          })
          await refreshResumes()
        }

        setPipelineState((prev) =>
          prev
            ? {
                ...prev,
                status: 'completed',
                currentStepIndex: 4,
                statusMessage: `Pipeline complete: Successfully processed ${newResumes} candidate resume(s). Ready for candidate shortlisting.`,
              }
            : null,
        )

        setZohoFeedback({
          type: 'success',
          message: `Successfully imported and processed ${newResumes} new resume(s). ${alreadyFetched} previously imported resumes were skipped.`,
        })
      }
    } catch (err: any) {
      const errMsg = err?.message || 'Failed to sync candidate resumes from Zoho.'
      setPipelineState((prev) =>
        prev
          ? {
              ...prev,
              status: 'failed',
              errorMessage: errMsg,
              statusMessage: `Pipeline error: ${errMsg}`,
            }
          : null,
      )
      setZohoFeedback({
        type: 'error',
        message: errMsg,
      })
    } finally {
      setIsZohoSyncing(false)
    }
  }

  // Auto-detect Zoho job info from existing project documents if zohoSummary is not yet set
  useEffect(() => {
    if (!zohoSummary && projectDocs.length > 0) {
      const zohoDocs = projectDocs.filter(
        (d) => d.metadata_json?.zoho_job_opening_id || d.metadata_json?.zoho_attachment_id
      )
      if (zohoDocs.length > 0) {
        const first = zohoDocs[0]
        const openingCode = String(first.metadata_json?.zoho_job_opening_code || '')
        const openingId = String(first.metadata_json?.zoho_job_opening_id || '')
        setZohoSummary({
          jobOpeningTitle: 'SRE Engineer',
          jobOpeningCode: openingCode || 'CD_39_JOB',
          jobId: openingId,
          totalFound: zohoDocs.length,
          alreadyFetched: zohoDocs.length,
          newResumes: 0,
          failedResumes: zohoDocs.filter((d) => d.processing_status === 'FAILED').length,
        })
      }
    }
  }, [projectDocs, zohoSummary])

  const handleRemoveResume = async (id: string) => {
    if (deletingResumeIds.has(id)) return
    const projectId = state.projectId
    if (!projectId) {
      setDeleteError('No active project found.')
      return
    }

    // Check if the item has been persisted to the backend
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
    const isPersisted = isUuid || projectDocs.some((d) => d.id === id)

    // For transient frontend-only items (e.g. pending-resume-* or client failed items), remove immediately from local state
    if (!isPersisted) {
      dispatch({ type: 'REMOVE_RESUME', payload: id })
      return
    }

    setDeletingResumeIds((prev) => new Set(prev).add(id))
    setDeleteError(null)

    try {
      // Call backend DELETE endpoint
      await api.deleteResume(projectId, id)

      // Update local state ONLY after successful API deletion
      dispatch({ type: 'REMOVE_RESUME', payload: id })
      setProjectDocs((prev) => prev.filter((doc) => doc.id !== id))
      setProfiles((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to delete resume.'
      setDeleteError(`Could not remove resume: ${msg}`)
    } finally {
      setDeletingResumeIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const handleRetryResume = async (id: string) => {
    if (retryingResumeIds.has(id) || deletingResumeIds.has(id)) return
    const projectId = state.projectId
    if (!projectId) {
      setUploadError('No active project found.')
      return
    }

    setRetryingResumeIds((prev) => new Set(prev).add(id))
    setRetryFeedback(null)

    // Mark status in local state as in-progress
    upsertProcessing({
      documentId: id,
      phase: 'parsing',
      status: 'IN_PROGRESS',
      stage: 'PARSING',
      normalized: false,
      errorMessage: undefined,
    })
    patchResumeFile(id, {
      status: 'processing',
      statusLabel: 'IN_PROGRESS',
      errorMessage: undefined,
    })

    try {
      const res = await api.retryResume(projectId, id)

      // On successful retry completion
      upsertProcessing({
        documentId: id,
        phase: 'normalized',
        status: res.processing_status || 'COMPLETED',
        stage: res.processing_stage || 'COMPLETED',
        normalized: true,
        errorMessage: undefined,
      })
      patchResumeFile(id, {
        status: 'done',
        statusLabel: res.processing_status || 'COMPLETED',
        errorMessage: undefined,
      })

      // Fetch normalized candidate profile so it displays in candidate profiles list
      try {
        const [normalizedRes, extractedRes] = await Promise.all([
          api.getNormalizedDocument(id),
          api.getExtractedDocument(id).catch(() => null),
        ])
        const normalized = (normalizedRes && 'data' in normalizedRes) ? (normalizedRes as any).data : normalizedRes
        const extracted = (extractedRes && 'data' in extractedRes) ? (extractedRes as any).data : extractedRes

        if (normalized && typeof normalized === 'object' && 'job_titles' in normalized) {
          setProfiles((prev) => ({
            ...prev,
            [id]: {
              normalized,
              extracted: extracted && typeof extracted === 'object' && 'candidate_name' in extracted ? extracted : null,
              loading: false,
            },
          }))
        }
      } catch {
        // Fallback handled by profiles useEffect
      }

      setRetryFeedback({
        id,
        type: 'success',
        message: `Resume "${res.filename || 'Candidate'}" retried and processed successfully.`,
      })
      await refreshResumes()
    } catch (err) {
      const msg = errorMessage(err, 'Resume retry failed')
      upsertProcessing({
        documentId: id,
        phase: 'failed',
        status: 'FAILED',
        stage: 'FAILED',
        normalized: false,
        errorMessage: msg,
      })
      patchResumeFile(id, {
        status: 'error',
        statusLabel: 'FAILED',
        errorMessage: msg,
      })
      setRetryFeedback({
        id,
        type: 'error',
        message: `Retry failed: ${msg}`,
      })
    } finally {
      setRetryingResumeIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const [isPreparingShortlist, setIsPreparingShortlist] = useState(false)

  const handleMoveToShortlisting = () => {
    if (!canProceedResumes || !state.projectId || busy || isPreparingShortlist) return
    setIsPreparingShortlist(true)
    setUploadError(null)
    const projectId = state.projectId

    completeAndAdvance()
    // Immediate responsive transition to Candidate Shortlisting
    navigate(`/projects/${projectId}/rankings`, {
      state: { triggerScoring: true },
    })
  }

  const handleBack = () => {
    navigate('/dashboard')
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

        <button
          type="button"
          onClick={() => setIsZohoModalOpen(true)}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 hover:from-amber-400 hover:to-orange-400 shadow-sm transition-all disabled:opacity-50"
        >
          {isZohoSyncing ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              <span>Syncing from Zoho…</span>
            </>
          ) : (
            <>
              <Sparkles size={16} />
              <span>Sync Applicants from Zoho</span>
            </>
          )}
        </button>
      </motion.div>

      {/* Resume Processing Pipeline Steps Card */}
      <AnimatePresence>
        {pipelineState && (
          <motion.div
            key="processing-pipeline-banner"
            initial={{ opacity: 0, y: -12, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -12, scale: 0.98 }}
            transition={{ duration: 0.3 }}
            className="mb-6 overflow-hidden rounded-2xl border border-sky-500/30 bg-gradient-to-br from-slate-900 via-slate-900 to-slate-950 p-5 shadow-xl shadow-sky-500/5 text-slate-100"
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3 mb-4">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-xl border ${
                    pipelineState.status === 'running'
                      ? 'bg-sky-500/20 text-sky-400 border-sky-500/30'
                      : pipelineState.status === 'completed'
                        ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                        : 'bg-rose-500/20 text-rose-400 border-rose-500/30'
                  }`}
                >
                  {pipelineState.status === 'running' ? (
                    <Loader2 size={18} className="animate-spin text-sky-400" />
                  ) : pipelineState.status === 'completed' ? (
                    <CheckCircle2 size={18} className="text-emerald-400" />
                  ) : (
                    <AlertCircle size={18} className="text-rose-400" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-bold tracking-tight text-white flex items-center gap-2">
                      <span>Resume Processing Steps</span>
                    </h3>
                    <span
                      className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border ${
                        pipelineState.status === 'running'
                          ? 'bg-sky-500/15 border-sky-500/30 text-sky-400'
                          : pipelineState.status === 'completed'
                            ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                            : 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                      }`}
                    >
                      {pipelineState.status === 'running'
                        ? `Step 0${pipelineState.currentStepIndex} of 04 • Active`
                        : pipelineState.status === 'completed'
                          ? 'All Steps Complete'
                          : 'Processing Paused'}
                    </span>
                    {pipelineState.jobCode && (
                      <span className="font-mono text-[11px] text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                        {pipelineState.jobCode}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Job Opening: <span className="font-semibold text-slate-200">{pipelineState.jobTitle}</span>
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/80 border border-slate-700/80 text-xs font-mono font-bold text-sky-400">
                  <span>{calculateProgressPercent(pipelineState)}%</span>
                </div>
                {pipelineState.status !== 'running' && (
                  <button
                    type="button"
                    onClick={() => setPipelineState(null)}
                    className="text-xs text-slate-400 hover:text-slate-200 transition-colors px-2 py-1 rounded-md hover:bg-slate-800"
                  >
                    Dismiss
                  </button>
                )}
              </div>
            </div>

            {/* Progress Track */}
            <div className="w-full bg-slate-800/80 rounded-full h-1.5 mb-5 overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ease-out rounded-full ${
                  pipelineState.status === 'failed'
                    ? 'bg-rose-500'
                    : pipelineState.status === 'completed'
                      ? 'bg-gradient-to-r from-sky-400 via-amber-400 to-emerald-400'
                      : 'bg-gradient-to-r from-sky-500 to-amber-500'
                }`}
                style={{ width: `${calculateProgressPercent(pipelineState)}%` }}
              />
            </div>

            {/* 4 Steps Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              {PIPELINE_STEPS.map((step) => {
                const stepStatus = getStepStatus(step.id, pipelineState)
                const StepIcon = step.icon
                return (
                  <div
                    key={step.id}
                    className={`rounded-xl border p-3 flex flex-col justify-between transition-all ${
                      stepStatus === 'in_progress'
                        ? 'bg-sky-500/10 border-sky-500/40 shadow-sm shadow-sky-500/10 ring-1 ring-sky-500/20'
                        : stepStatus === 'completed'
                          ? 'bg-emerald-950/20 border-emerald-500/30'
                          : stepStatus === 'skipped'
                            ? 'bg-slate-900/60 border-slate-800 text-slate-400'
                            : 'bg-slate-950/40 border-slate-800/80 text-slate-500'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                          <StepIcon size={12} className={stepStatus === 'in_progress' ? 'text-sky-400' : 'text-slate-500'} />
                          Step 0{step.id}
                        </span>
                        {stepStatus === 'in_progress' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-bold text-sky-400 bg-sky-400/10 px-1.5 py-0.5 rounded-full border border-sky-400/20">
                            <Loader2 size={10} className="animate-spin" /> In Progress
                          </span>
                        ) : stepStatus === 'completed' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded-full border border-emerald-400/20">
                            <CheckCircle2 size={10} /> Completed
                          </span>
                        ) : stepStatus === 'skipped' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded-full border border-slate-700">
                            Up to date
                          </span>
                        ) : (
                          <span className="text-[10px] font-medium text-slate-600">Pending</span>
                        )}
                      </div>

                      <h4
                        className={`text-xs font-bold leading-tight mb-1 ${
                          stepStatus === 'in_progress'
                            ? 'text-white'
                            : stepStatus === 'completed'
                              ? 'text-slate-200'
                              : 'text-slate-400'
                        }`}
                      >
                        {step.title}
                      </h4>
                      <p className="text-[11px] text-slate-400 leading-snug">
                        {step.shortDesc}
                      </p>
                    </div>

                    <div className="mt-3 pt-2 border-t border-slate-800/60 text-[10px]">
                      {stepStatus === 'in_progress' && (
                        <span className="text-sky-400 font-medium">
                          {step.id === 1 && 'Querying Zoho API & checking duplicates…'}
                          {step.id === 2 && `Parsing raw text (${pipelineState.currentDocIndex ?? 1} of ${pipelineState.totalDocs ?? 1})…`}
                          {step.id === 3 && `Extracting candidate data (${pipelineState.currentDocIndex ?? 1} of ${pipelineState.totalDocs ?? 1})…`}
                          {step.id === 4 && `Normalizing profile (${pipelineState.currentDocIndex ?? 1} of ${pipelineState.totalDocs ?? 1})…`}
                        </span>
                      )}
                      {stepStatus === 'completed' && (
                        <span className="text-emerald-400 font-medium">
                          {step.id === 1 && (pipelineState.newResumes !== undefined
                            ? `${pipelineState.newResumes} new (${pipelineState.alreadyFetched ?? 0} skipped)`
                            : 'Attachments synced & verified')}
                          {step.id === 2 && 'Text extraction complete'}
                          {step.id === 3 && 'Candidate entities extracted'}
                          {step.id === 4 && 'Profile ready for shortlisting'}
                        </span>
                      )}
                      {stepStatus === 'skipped' && (
                        <span className="text-slate-400">Already completed (Idempotent)</span>
                      )}
                      {stepStatus === 'pending' && (
                        <span className="text-slate-600">Waiting for previous step…</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Live Status Ticker */}
            <div className="rounded-xl bg-slate-950/70 border border-slate-800/80 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2.5 min-w-0">
                {pipelineState.status === 'running' ? (
                  <span className="flex h-2 w-2 relative shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500" />
                  </span>
                ) : pipelineState.status === 'completed' ? (
                  <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle size={14} className="text-rose-400 shrink-0" />
                )}
                <span className="truncate text-slate-300 font-medium">
                  {pipelineState.statusMessage}
                </span>
              </div>

              {pipelineState.totalFound !== undefined && (
                <div className="flex items-center gap-3 text-[11px] text-slate-400 shrink-0">
                  <span>
                    Total found: <strong className="text-slate-200 font-mono">{pipelineState.totalFound}</strong>
                  </span>
                  <span>•</span>
                  <span>
                    Skipped: <strong className="text-sky-400 font-mono">{pipelineState.alreadyFetched ?? 0}</strong>
                  </span>
                  <span>•</span>
                  <span>
                    New: <strong className="text-emerald-400 font-mono">{pipelineState.newResumes ?? 0}</strong>
                  </span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Zoho Resume Fetch Summary Card */}
      {zohoSummary && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 overflow-hidden rounded-2xl border border-amber-500/30 bg-gradient-to-br from-slate-900/95 via-slate-900 to-slate-950 p-5 shadow-xl shadow-amber-500/5 text-slate-100"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3 mb-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
                <Briefcase size={16} />
              </div>
              <div>
                <h3 className="text-sm font-bold tracking-tight text-white flex items-center gap-2">
                  <span>Resume Fetch Summary</span>
                  <span className="text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                    Zoho Recruit
                  </span>
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Job Opening:{' '}
                  <span className="font-semibold text-slate-200">{zohoSummary.jobOpeningTitle}</span>
                  {zohoSummary.jobOpeningCode && (
                    <span className="ml-1.5 font-mono text-[11px] text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                      {zohoSummary.jobOpeningCode}
                    </span>
                  )}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setZohoSummary(null)}
              className="text-xs text-slate-400 hover:text-slate-200 transition-colors px-2 py-1 rounded-md hover:bg-slate-800"
            >
              Dismiss
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
            {/* Metric 1: Total Resumes Found */}
            <div className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3.5 flex flex-col justify-between">
              <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1">
                Total resumes found in this Job Opening
              </p>
              <div className="flex items-baseline gap-2 mt-auto">
                <span className="text-2xl font-black tracking-tight text-slate-100 font-mono">
                  {zohoSummary.totalFound}
                </span>
                <span className="text-xs text-slate-500">eligible resumes</span>
              </div>
            </div>

            {/* Metric 2: Already Fetched Resumes */}
            <div className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3.5 flex flex-col justify-between">
              <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1">
                Already fetched resumes
              </p>
              <div className="flex items-baseline gap-2 mt-auto">
                <span className="text-2xl font-black tracking-tight text-sky-400 font-mono">
                  {zohoSummary.alreadyFetched}
                </span>
                <span className="text-xs text-slate-500">previously imported</span>
              </div>
            </div>

            {/* Metric 3: New Resumes */}
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/20 p-3.5 flex flex-col justify-between">
              <p className="text-[11px] font-medium text-emerald-400 uppercase tracking-wider mb-1">
                New resumes
              </p>
              <div className="flex items-baseline gap-2 mt-auto">
                <span className="text-2xl font-black tracking-tight text-emerald-300 font-mono">
                  {zohoSummary.newResumes}
                </span>
                <span className="text-xs text-emerald-500/80">newly imported</span>
              </div>
            </div>
          </div>

          {zohoSummary.failedResumes > 0 && (
            <div className="mb-3 px-3 py-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
              <AlertCircle size={14} className="shrink-0 text-rose-400" />
              <span>{zohoSummary.failedResumes} resume file(s) failed download or saving.</span>
            </div>
          )}

          <div className="text-xs text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/60">
            <span>
              {zohoSummary.newResumes === 0
                ? 'All eligible candidate resumes are up to date. Previously completed profiles were not reprocessed.'
                : `Imported ${zohoSummary.newResumes} new candidate resume(s). Only newly imported resumes enter the processing pipeline.`}
            </span>
          </div>
        </motion.div>
      )}

      {/* Zoho Feedback Notification */}
      {zohoFeedback && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`mb-4 p-4 rounded-xl border flex items-center justify-between gap-3 text-xs ${
            zohoFeedback.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-rose-50 border-rose-200 text-rose-800'
          }`}
        >
          <div className="flex items-center gap-2.5">
            {zohoFeedback.type === 'success' ? (
              <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
            ) : (
              <AlertCircle size={18} className="text-rose-600 shrink-0" />
            )}
            <span className="font-medium">{zohoFeedback.message}</span>
          </div>
          <button
            type="button"
            onClick={() => setZohoFeedback(null)}
            className="text-xs font-bold underline opacity-70 hover:opacity-100"
          >
            Dismiss
          </button>
        </motion.div>
      )}

      {/* When Zoho candidates were already imported and skipped, show clear banner */}
      {zohoSummary && zohoSummary.alreadyFetched > 0 && projectDocs.length === 0 && (
        <motion.div
          variants={fadeUp}
          className="mb-6 rounded-2xl border border-sky-200 bg-sky-50/50 p-6 text-center shadow-xs"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-100 text-sky-600 mb-3 shadow-xs">
            <CheckCircle2 size={24} />
          </div>
          <h3 className="text-sm font-bold text-slate-800">No New Resumes to Display</h3>
          <p className="mt-1 text-xs text-slate-500 max-w-md mx-auto">
            All {zohoSummary.alreadyFetched} candidate resumes from Zoho Job Opening ({zohoSummary.jobOpeningCode || zohoSummary.jobOpeningTitle}) were already imported and deduplicated. Only new resumes are displayed for screening.
          </p>
        </motion.div>
      )}



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
          deletingIds={deletingResumeIds}
          retryingIds={retryingResumeIds}
          onSelectFiles={handleResumeSelect}
          onRemove={handleRemoveResume}
          onRetry={handleRetryResume}
          disabled={busy}
        />
        {retryFeedback && (
          <div
            className={`mt-2.5 p-3 rounded-xl border flex items-center justify-between text-xs font-medium ${
              retryFeedback.type === 'success'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-rose-50 border-rose-200 text-rose-800'
            }`}
          >
            <div className="flex items-center gap-2">
              {retryFeedback.type === 'success' ? (
                <CheckCircle2 size={15} className="text-emerald-600 shrink-0" />
              ) : (
                <AlertCircle size={15} className="text-rose-600 shrink-0" />
              )}
              <span>{retryFeedback.message}</span>
            </div>
            <button
              type="button"
              onClick={() => setRetryFeedback(null)}
              className="text-[11px] underline opacity-70 hover:opacity-100 ml-2 cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        )}
        {isUploading && (
          <p className="mt-2 text-[12px] text-sky-600 text-center font-medium">
            Uploading resumes…
          </p>
        )}
        {uploadError && (
          <p className="mt-2 text-[12px] text-red-500 text-center">{uploadError}</p>
        )}
        {deleteError && (
          <p className="mt-2 text-[12px] text-red-500 text-center font-medium">{deleteError}</p>
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

      {uploadError && (
        <motion.div variants={fadeUp} className="rounded-xl border border-red-200 bg-red-50 p-4 text-[13px] text-red-700 mb-4">
          {uploadError}
        </motion.div>
      )}

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
            Back to Dashboard
          </motion.button>

          <motion.button
            onClick={handleMoveToShortlisting}
            disabled={!canProceedResumes || busy || isPreparingShortlist}
            whileHover={canProceedResumes && !busy && !isPreparingShortlist ? { scale: 1.02 } : undefined}
            whileTap={canProceedResumes && !busy && !isPreparingShortlist ? { scale: 0.98 } : undefined}
            className={`flex-1 sm:flex-initial py-2.5 px-6 rounded-xl text-[13px] font-semibold flex items-center justify-center gap-2 transition-all shadow-sky-sm ${
              canProceedResumes && !busy && !isPreparingShortlist
                ? 'bg-sky-600 hover:bg-sky-700 text-white cursor-pointer'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed border-transparent shadow-none'
            }`}
          >
            {isPreparingShortlist ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                <span>Preparing Candidate Shortlisting…</span>
              </>
            ) : (
              <>
                <span>Move to Candidate Shortlisting</span>
                <ArrowRight size={15} />
              </>
            )}
          </motion.button>
        </div>
      </motion.div>

      {/* Zoho Recruit Sync Applicants Modal */}
      <ZohoImportModal
        isOpen={isZohoModalOpen}
        onClose={() => setIsZohoModalOpen(false)}
        mode="applicants"
        onSelectJob={handleSelectZohoJob}
        isProcessing={isZohoSyncing}
        selectedJobId={selectedZohoJobId}
      />
    </motion.div>
  )
}

