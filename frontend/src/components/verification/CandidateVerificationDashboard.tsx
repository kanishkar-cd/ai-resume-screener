import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Search,
  Filter,
  Users,
  ChevronRight,
  ExternalLink,
  Briefcase,
  Mail,
  Phone,
  FileText,
  AlertCircle,
  HelpCircle,
  Loader2,
  Clock,
  ArrowRight,
  X,
  RotateCcw,
} from 'lucide-react'
import {
  api,
  ApiError,
  type BatchVerificationSummary,
  type CandidateVerificationItemResult,
  type CandidateVerificationStatus,
  type CandidateIdentityStatus,
  type RepeatApplicationStatus,
  type Document,
  type ManualReviewDecision,
} from '@/api'

interface CandidateVerificationDashboardProps {
  projectId: string
  jobOpeningId?: string
  onClose?: () => void
}

export default function CandidateVerificationDashboard({
  projectId,
  jobOpeningId,
  onClose,
}: CandidateVerificationDashboardProps) {
  // ── State ───────────────────────────────────────────────────────────────────
  const [summary, setSummary] = useState<BatchVerificationSummary | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [isVerifying, setIsVerifying] = useState(false)
  const [isRetrying, setIsRetrying] = useState(false)
  const [isSubmittingReview, setIsSubmittingReview] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [repeatFilter, setRepeatFilter] = useState<string>('ALL')
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateVerificationItemResult | null>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [manualReviewNote, setManualReviewNote] = useState('')
  const [manualReviewError, setManualReviewError] = useState<string | null>(null)
  const [manualReviewSuccess, setManualReviewSuccess] = useState<string | null>(null)

  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // ── Document Map & Verification Status ──────────────────────────────────────
  const documentMap = useMemo(() => {
    const map = new Map<string, Document>()
    for (const doc of documents) {
      map.set(doc.id, doc)
    }
    return map
  }, [documents])

  const getDocVerificationStatus = useCallback(
    (docId: string): CandidateVerificationStatus => {
      const doc = documentMap.get(docId)
      const persisted = (doc?.metadata_json as Record<string, any> | undefined)?.verification?.verification_status
      if (persisted) return persisted as CandidateVerificationStatus
      if (
        selectedCandidate &&
        selectedCandidate.document_ids.includes(docId) &&
        selectedCandidate.document_ids.length === 1
      ) {
        return selectedCandidate.verification_status
      }
      return 'PENDING'
    },
    [documentMap, selectedCandidate],
  )

  // ── Fetch Status ────────────────────────────────────────────────────────────
  const fetchStatus = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      setError(null)
      try {
        const [summaryData, resumesRes] = await Promise.all([
          api.getProjectVerificationStatus(projectId),
          api.listProjectResumes(projectId).catch(() => ({ items: [] as Document[], total: 0 })),
        ])
        setSummary(summaryData)
        if (resumesRes && Array.isArray(resumesRes.items)) {
          setDocuments(resumesRes.items)
        }
        return summaryData
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : 'Unable to load candidate verification status.'
        setError(msg)
        return null
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [projectId],
  )

  // Initial load on mount
  useEffect(() => {
    void fetchStatus()
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [fetchStatus])

  // Synchronize selected document when candidate changes
  useEffect(() => {
    if (selectedCandidate && selectedCandidate.document_ids.length > 0) {
      const reviewReqDoc = selectedCandidate.document_ids.find(
        (id) => getDocVerificationStatus(id) === 'REVIEW_REQUIRED',
      )
      setSelectedDocId(reviewReqDoc || selectedCandidate.document_ids[0])
      setManualReviewNote('')
      setManualReviewError(null)
      setManualReviewSuccess(null)
    } else {
      setSelectedDocId(null)
      setManualReviewNote('')
      setManualReviewError(null)
      setManualReviewSuccess(null)
    }
  }, [selectedCandidate, getDocVerificationStatus])

  // Polling when batch is in progress
  useEffect(() => {
    if (summary?.status === 'IN_PROGRESS') {
      if (!pollingRef.current) {
        pollingRef.current = setInterval(async () => {
          const updated = await fetchStatus(true)
          if (updated && updated.status !== 'IN_PROGRESS') {
            if (pollingRef.current) clearInterval(pollingRef.current)
            pollingRef.current = null
            setIsVerifying(false)
            setIsRetrying(false)
          }
        }, 2500)
      }
    } else {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [summary?.status, fetchStatus])

  // ── Actions ─────────────────────────────────────────────────────────────────
  const handleVerifyAll = async (force = false) => {
    if (isVerifying || isRetrying) return
    setIsVerifying(true)
    setError(null)
    try {
      const updated = await api.verifyProjectCandidates(projectId, force)
      setSummary(updated)
      await fetchStatus(true)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Verification request failed.'
      setError(msg)
    } finally {
      setIsVerifying(false)
    }
  }

  const handleRetryFailed = async () => {
    if (isVerifying || isRetrying) return
    setIsRetrying(true)
    setError(null)
    try {
      const updated = await api.retryProjectCandidateVerification(projectId)
      setSummary(updated)
      await fetchStatus(true)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Retry request failed.'
      setError(msg)
    } finally {
      setIsRetrying(false)
    }
  }

  const handleManualReviewAction = async (decision: ManualReviewDecision) => {
    if (!selectedDocId || isSubmittingReview) return
    setManualReviewError(null)
    setManualReviewSuccess(null)
    setIsSubmittingReview(true)

    try {
      await api.reviewCandidateDocument(projectId, selectedDocId, {
        decision,
        review_note: manualReviewNote.trim() || null,
      })

      setManualReviewSuccess(
        `Document decision (${decision}) submitted successfully. Persisted status updated.`,
      )
      setManualReviewNote('')

      // Refresh backend verification state immediately
      const refreshedSummary = await fetchStatus(true)
      if (refreshedSummary?.results) {
        const updatedCandidate = refreshedSummary.results.find(
          (c) =>
            c.document_ids.includes(selectedDocId) ||
            c.candidate_identifier === selectedCandidate?.candidate_identifier,
        )
        if (updatedCandidate) {
          setSelectedCandidate(updatedCandidate)
        }
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Manual review decision failed to persist.'
      setManualReviewError(msg)
    } finally {
      setIsSubmittingReview(false)
    }
  }


  // ── Filtered Candidate Results ──────────────────────────────────────────────
  const candidates = useMemo(() => {
    if (!summary?.results) return []
    return summary.results.filter((c) => {
      // Search filter
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch =
        !q ||
        (c.candidate_name && c.candidate_name.toLowerCase().includes(q)) ||
        (c.email && c.email.toLowerCase().includes(q)) ||
        (c.phone && c.phone.includes(q)) ||
        (c.zoho_candidate_id && c.zoho_candidate_id.toLowerCase().includes(q))

      // Status filter
      const matchesStatus =
        statusFilter === 'ALL' ||
        c.verification_status === statusFilter ||
        (statusFilter === 'REVIEW' && c.verification_status === 'REVIEW_REQUIRED')

      // Repeat filter
      const matchesRepeat =
        repeatFilter === 'ALL' ||
        (repeatFilter === 'REPEAT_ONLY' && c.is_repeat_applicant) ||
        (repeatFilter === 'FIRST_ONLY' && !c.is_repeat_applicant) ||
        c.repeat_application_status === repeatFilter

      return matchesSearch && matchesStatus && matchesRepeat
    })
  }, [summary?.results, searchQuery, statusFilter, repeatFilter])

  // ── Badges & Formatting ─────────────────────────────────────────────────────
  const getVerificationBadge = (status: CandidateVerificationStatus) => {
    switch (status) {
      case 'VERIFIED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 size={12} className="text-emerald-500" />
            Verified
          </span>
        )
      case 'REVIEW_REQUIRED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-50 text-amber-800 border border-amber-200">
            <AlertTriangle size={12} className="text-amber-600" />
            Review Required
          </span>
        )
      case 'REJECTED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-rose-50 text-rose-800 border border-rose-200">
            <XCircle size={12} className="text-rose-600" />
            Rejected
          </span>
        )
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle size={12} className="text-rose-500" />
            Failed
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-slate-100 text-slate-600 border border-slate-200">
            <Clock size={12} className="text-slate-400" />
            Pending
          </span>
        )
    }
  }

  const getIdentityBadge = (status?: CandidateIdentityStatus | null) => {
    switch (status) {
      case 'EXISTING_CANDIDATE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
            Existing Candidate
          </span>
        )
      case 'NEW_CANDIDATE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            New Candidate
          </span>
        )
      case 'REVIEW_REQUIRED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            Ambiguous Identity
          </span>
        )
      default:
        return <span className="text-[10px] text-slate-400">—</span>
    }
  }

  const getRepeatBadge = (status?: RepeatApplicationStatus | null, isRepeat?: boolean) => {
    switch (status) {
      case 'FIRST_APPLICATION':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-50 text-slate-600 border border-slate-200">
            1st Application
          </span>
        )
      case 'REPEAT_APPLICATION_SAME_JOB':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
            Prior Applicant (Same Job)
          </span>
        )
      case 'REPEAT_APPLICATION_DIFFERENT_JOB':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-50 text-sky-700 border border-sky-200">
            Prior Applicant (Other Job)
          </span>
        )
      case 'MULTIPLE_PREVIOUS_APPLICATIONS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-50 text-purple-700 border border-purple-200">
            Multiple Applications
          </span>
        )
      case 'JOB_OPENING_REQUIRED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-500 border border-slate-200">
            Job Opening Required
          </span>
        )
      default:
        return isRepeat ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-50 text-sky-700 border border-sky-200">
            Repeat Applicant
          </span>
        ) : (
          <span className="text-[10px] text-slate-400">—</span>
        )
    }
  }

  return (
    <div className="w-full max-w-7xl mx-auto space-y-6 pb-12">
      {/* ── Top Header ───────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
              <ShieldCheck size={20} />
            </div>
            <div>
              <h2 className="text-xl font-extrabold text-slate-900 tracking-tight">
                Candidate Identity & Repeat Application Verification
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Deterministic ATS identity matching and multi-job application history.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          {summary && (summary.failed_candidates > 0 || summary.review_required_candidates > 0) && (
            <button
              type="button"
              onClick={handleRetryFailed}
              disabled={isVerifying || isRetrying}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-bold rounded-xl border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
            >
              {isRetrying ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
              <span>Retry Failed ({summary.failed_candidates + summary.review_required_candidates})</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => void fetchStatus(false)}
            disabled={loading || isVerifying}
            className="p-2 text-slate-600 border border-slate-200 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer disabled:opacity-50"
            title="Refresh Status"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>

          <button
            type="button"
            onClick={() => void handleVerifyAll(false)}
            disabled={isVerifying || isRetrying}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow-xs cursor-pointer disabled:opacity-50"
          >
            {isVerifying ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                <span>Verifying Candidates…</span>
              </>
            ) : (
              <>
                <ShieldCheck size={15} />
                <span>Verify All Candidates</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Error Banner ──────────────────────────────────────────────────────── */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 flex items-center justify-between text-xs text-rose-800">
          <div className="flex items-center gap-2.5">
            <AlertCircle size={16} className="text-rose-600 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => void fetchStatus()}
            className="font-bold underline hover:text-rose-900 cursor-pointer ml-4"
          >
            Try Again
          </button>
        </div>
      )}

      {/* ── Metric Stat Cards ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
        {/* Total Candidates */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider">Total</span>
            <Users size={15} />
          </div>
          <p className="text-2xl font-black text-slate-900">{summary?.total_candidates ?? 0}</p>
          <span className="text-[10px] text-slate-400">Grouped applicant units</span>
        </div>

        {/* Processed Candidates */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="flex items-center justify-between text-blue-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Processed</span>
            <CheckCircle2 size={15} />
          </div>
          <p className="text-2xl font-black text-slate-900">{summary?.processed_candidates ?? 0}</p>
          <span className="text-[10px] text-slate-400">
            {summary?.progress_percentage !== undefined ? `${summary.progress_percentage.toFixed(0)}% evaluated` : '0%'}
          </span>
        </div>

        {/* Verified Candidates */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="flex items-center justify-between text-emerald-600 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Verified</span>
            <ShieldCheck size={15} />
          </div>
          <p className="text-2xl font-black text-emerald-600">{summary?.verified_candidates ?? 0}</p>
          <span className="text-[10px] text-slate-400">Clean deterministic match</span>
        </div>

        {/* Review Required Candidates */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="flex items-center justify-between text-amber-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Review Required</span>
            <AlertTriangle size={15} />
          </div>
          <p className="text-2xl font-black text-amber-600">{summary?.review_required_candidates ?? 0}</p>
          <span className="text-[10px] text-slate-400">Identity ambiguity</span>
        </div>

        {/* Failed Candidates */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="flex items-center justify-between text-rose-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Failed</span>
            <XCircle size={15} />
          </div>
          <p className="text-2xl font-black text-rose-600">{summary?.failed_candidates ?? 0}</p>
          <span className="text-[10px] text-slate-400">System errors</span>
        </div>
      </div>

      {/* ── Progress Bar ──────────────────────────────────────────────────────── */}
      {summary && summary.total_candidates > 0 && (
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-1.5">
          <div className="flex justify-between items-center text-xs">
            <span className="font-semibold text-slate-700">Verification Progress</span>
            <span className="font-bold text-slate-900">{summary.progress_percentage.toFixed(0)}%</span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
            <div
              className="bg-gradient-to-r from-blue-600 to-emerald-500 h-2.5 rounded-full transition-all duration-500"
              style={{ width: `${summary.progress_percentage}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Policy Note ───────────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-sky-100 bg-sky-50/60 p-3.5 flex items-start gap-2.5 text-[11px] text-sky-800">
        <HelpCircle size={15} className="text-sky-600 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          <strong className="font-bold">Applicant History Policy:</strong> Repeat applications across multiple job
          openings represent past application events and are strictly kept separate from identity verification or fraud
          decisions. A repeat applicant is not penalized in screening.
        </p>
      </div>

      {/* ── Filter & Search Toolbar ───────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200 shadow-2xs">
        <div className="relative w-full sm:w-80">
          <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
          <input
            type="text"
            placeholder="Search candidate, email, phone, Zoho ID…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-blue-500 bg-slate-50/50"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-700 font-medium focus:outline-none focus:border-blue-500"
          >
            <option value="ALL">All Verification Statuses</option>
            <option value="VERIFIED">Verified</option>
            <option value="REVIEW">Review Required</option>
            <option value="REJECTED">Rejected</option>
            <option value="FAILED">Failed</option>
          </select>

          {/* Repeat Filter */}
          <select
            value={repeatFilter}
            onChange={(e) => setRepeatFilter(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-700 font-medium focus:outline-none focus:border-blue-500"
          >
            <option value="ALL">All Application Types</option>
            <option value="FIRST_APPLICATION">1st Application</option>
            <option value="REPEAT_APPLICATION_SAME_JOB">Repeat (Same Job)</option>
            <option value="REPEAT_APPLICATION_DIFFERENT_JOB">Repeat (Other Job)</option>
            <option value="MULTIPLE_PREVIOUS_APPLICATIONS">Multiple Applications</option>
          </select>
        </div>
      </div>

      {/* ── Candidate Table ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        {loading && !summary ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-slate-400">
            <Loader2 size={24} className="animate-spin text-blue-600" />
            <p className="text-xs font-medium">Loading candidate verification records…</p>
          </div>
        ) : candidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-center px-4">
            <ShieldCheck size={36} className="text-slate-300" />
            <h3 className="text-sm font-bold text-slate-700">No Candidate Records Found</h3>
            <p className="text-xs text-slate-500 max-w-sm">
              {summary && summary.total_candidates === 0
                ? 'No candidate resumes have been uploaded for this job opening yet.'
                : 'No candidates matched the selected search or filter criteria.'}
            </p>
            {summary && summary.total_candidates === 0 && (
              <button
                type="button"
                onClick={() => void handleVerifyAll(false)}
                className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 transition-colors shadow-xs cursor-pointer"
              >
                <ShieldCheck size={13} />
                <span>Run Initial Verification</span>
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/70 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Candidate</th>
                  <th className="py-3 px-4">Files</th>
                  <th className="py-3 px-4">Identity Match</th>
                  <th className="py-3 px-4">Verification Status</th>
                  <th className="py-3 px-4">Application History</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {candidates.map((cand) => (
                  <tr
                    key={cand.candidate_identifier}
                    className="hover:bg-slate-50/60 transition-colors cursor-pointer group"
                    onClick={() => setSelectedCandidate(cand)}
                  >
                    {/* Candidate Name & Contact */}
                    <td className="py-3 px-4">
                      <div className="font-bold text-slate-900 group-hover:text-blue-600 transition-colors">
                        {cand.candidate_name || 'Unnamed Applicant'}
                      </div>
                      <div className="text-[11px] text-slate-500 flex items-center gap-2 mt-0.5 flex-wrap">
                        {cand.email && (
                          <span className="inline-flex items-center gap-1">
                            <Mail size={11} className="text-slate-400" />
                            {cand.email}
                          </span>
                        )}
                        {cand.phone && (
                          <span className="inline-flex items-center gap-1">
                            <Phone size={11} className="text-slate-400" />
                            {cand.phone}
                          </span>
                        )}
                        {cand.zoho_candidate_id && (
                          <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.2 rounded font-mono">
                            {cand.zoho_candidate_id}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Grouped Attachments */}
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-600">
                        <FileText size={10} className="text-slate-400" />
                        {cand.document_ids.length} {cand.document_ids.length === 1 ? 'file' : 'files'}
                      </span>
                    </td>

                    {/* Identity Match */}
                    <td className="py-3 px-4">{getIdentityBadge(cand.identity_status)}</td>

                    {/* Verification Status */}
                    <td className="py-3 px-4">{getVerificationBadge(cand.verification_status)}</td>

                    {/* Repeat Application History */}
                    <td className="py-3 px-4">
                      {getRepeatBadge(cand.repeat_application_status, cand.is_repeat_applicant)}
                    </td>

                    {/* Confidence */}
                    <td className="py-3 px-4">
                      <span className="font-semibold text-slate-700">
                        {cand.confidence !== undefined ? `${(cand.confidence * 100).toFixed(0)}%` : '—'}
                      </span>
                    </td>

                    {/* Action */}
                    <td className="py-3 px-4 text-right">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedCandidate(cand)
                        }}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                        title="View Verification Details"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Slide-Over Detail Drawer ────────────────────────────────────────── */}
      <AnimatePresence>
        {selectedCandidate && (
          <>
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedCandidate(null)}
              className="fixed inset-0 bg-slate-900/30 backdrop-blur-xs z-40"
            />

            <motion.div
              key="drawer"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 280 }}
              className="fixed right-0 top-0 bottom-0 w-full max-w-lg bg-white z-50 shadow-2xl flex flex-col overflow-hidden border-l border-slate-200"
            >
              {/* Header */}
              <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-white shrink-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
                    <ShieldCheck size={20} />
                  </div>
                  <div>
                    <h3 className="text-base font-extrabold text-slate-900">
                      {selectedCandidate.candidate_name || 'Candidate Verification'}
                    </h3>
                    <p className="text-xs text-slate-500">ID: {selectedCandidate.candidate_identifier}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedCandidate(null)}
                  className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Drawer Content */}
              <div className="flex-1 overflow-y-auto p-5 space-y-6">
                {/* Status Summary Banner */}
                <div className="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-500">Verification Outcome</span>
                    {getVerificationBadge(selectedCandidate.verification_status)}
                  </div>
                  <div className="flex items-center justify-between pt-1 text-xs">
                    <span className="text-slate-500">Identity Match</span>
                    {getIdentityBadge(selectedCandidate.identity_status)}
                  </div>
                  <div className="flex items-center justify-between pt-1 text-xs">
                    <span className="text-slate-500">Application Event</span>
                    {getRepeatBadge(
                      selectedCandidate.repeat_application_status,
                      selectedCandidate.is_repeat_applicant
                    )}
                  </div>
                </div>

                {/* Contact Information */}
                <div>
                  <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">
                    Contact Identifiers
                  </h4>
                  <div className="p-3.5 rounded-xl border border-slate-200 bg-white space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Email:</span>
                      <span className="font-semibold text-slate-800">{selectedCandidate.email || 'None'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Phone:</span>
                      <span className="font-semibold text-slate-800">{selectedCandidate.phone || 'None'}</span>
                    </div>
                    {selectedCandidate.zoho_candidate_id && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">Zoho Candidate ID:</span>
                        <span className="font-mono text-slate-800">{selectedCandidate.zoho_candidate_id}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Grouped Document Files */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Grouped Attachments ({selectedCandidate.document_ids.length})
                    </h4>
                    <span className="text-[10px] text-slate-500">Click attachment to select for review</span>
                  </div>
                  <div className="space-y-2">
                    {selectedCandidate.document_ids.map((docId, idx) => {
                      const docMeta = documentMap.get(docId)
                      const docStatus = getDocVerificationStatus(docId)
                      const isSelected = selectedDocId === docId
                      const filename = docMeta?.original_filename || `Document #${idx + 1}`

                      return (
                        <button
                          key={docId}
                          type="button"
                          onClick={() => {
                            setSelectedDocId(docId)
                            setManualReviewError(null)
                            setManualReviewSuccess(null)
                          }}
                          className={`w-full text-left flex items-center justify-between p-3 rounded-xl border transition-all cursor-pointer ${
                            isSelected
                              ? 'border-blue-500 bg-blue-50/50 ring-2 ring-blue-500/20 shadow-xs'
                              : 'border-slate-200 hover:border-slate-300 bg-slate-50/50'
                          }`}
                        >
                          <div className="flex items-center gap-2.5 min-w-0 pr-2">
                            <FileText size={15} className={isSelected ? 'text-blue-600 shrink-0' : 'text-slate-400 shrink-0'} />
                            <div className="min-w-0">
                              <p className="font-bold text-slate-800 text-xs truncate">{filename}</p>
                              <p className="text-[10px] text-slate-400 font-mono truncate">{docId}</p>
                            </div>
                          </div>
                          <div className="shrink-0 flex items-center gap-2">
                            {getVerificationBadge(docStatus)}
                            {isSelected && (
                              <span className="text-[10px] font-bold text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded">
                                Selected
                              </span>
                            )}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Match Reasons */}
                {selectedCandidate.reasons && selectedCandidate.reasons.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">Match Reasons</h4>
                    <ul className="space-y-1.5">
                      {selectedCandidate.reasons.map((r, i) => (
                        <li
                          key={i}
                          className="text-xs text-slate-700 bg-slate-50 p-2 rounded-lg border border-slate-200 flex items-start gap-2"
                        >
                          <CheckCircle2 size={13} className="text-emerald-500 shrink-0 mt-0.5" />
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Conflicts & Ambiguities */}
                {selectedCandidate.conflicts && selectedCandidate.conflicts.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-2">
                      Detected Identity Conflicts
                    </h4>
                    <div className="p-3.5 rounded-xl border border-amber-200 bg-amber-50/50 space-y-2">
                      {selectedCandidate.conflicts.map((c, i) => (
                        <div key={i} className="text-xs text-amber-900 space-y-1">
                          <div className="font-bold flex items-center gap-1.5">
                            <AlertTriangle size={13} className="text-amber-600" />
                            <span>{String(c.type || 'Identity Conflict')}</span>
                          </div>
                          <pre className="text-[10px] bg-white/80 p-2 rounded border border-amber-100 overflow-x-auto text-slate-700">
                            {JSON.stringify(c, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Application History */}
                <div>
                  <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">
                    Application History Across Openings
                  </h4>
                  {selectedCandidate.previous_applications && selectedCandidate.previous_applications.length > 0 ? (
                    <div className="space-y-2">
                      {selectedCandidate.previous_applications.map((app, i) => (
                        <div
                          key={i}
                          className="p-3 rounded-xl border border-slate-200 bg-white text-xs space-y-1 shadow-2xs"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-slate-800">{app.job_title || 'Job Opening'}</span>
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
                                app.is_same_job
                                  ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                                  : 'bg-sky-50 text-sky-700 border border-sky-200'
                              }`}
                            >
                              {app.is_same_job ? 'Same Job' : 'Other Job'}
                            </span>
                          </div>
                          <div className="text-slate-500 text-[11px] flex items-center gap-2">
                            <span>Opening ID: {app.job_opening_id || app.project_id || 'N/A'}</span>
                            {app.applied_at && <span>Applied: {String(app.applied_at).slice(0, 10)}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 italic p-3 rounded-xl border border-slate-100 bg-slate-50/50">
                      No previous applications found for this candidate in the ATS.
                    </p>
                  )}
                </div>

                {/* Manual Review Actions (Document-Targeted Override) */}
                {selectedDocId && (
                  <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/70 space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                        Manual Identity Review
                      </h4>
                      <span className="text-[10px] font-mono text-slate-500 bg-slate-200/70 px-2 py-0.5 rounded">
                        Target Document: {documentMap.get(selectedDocId)?.original_filename || selectedDocId.slice(0, 8) + '…'}
                      </span>
                    </div>

                    {getDocVerificationStatus(selectedDocId) === 'REVIEW_REQUIRED' ? (
                      <div className="space-y-3 pt-1">
                        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200/80 p-2.5 rounded-lg leading-relaxed">
                          This specific resume attachment was flagged for manual review because identity evidence was ambiguous or incomplete.
                          Your decision applies strictly to this document and will not automatically approve other attachments in the group.
                        </p>

                        <textarea
                          placeholder="Enter review decision reason or verification notes (optional)…"
                          value={manualReviewNote}
                          disabled={isSubmittingReview}
                          onChange={(e) => setManualReviewNote(e.target.value)}
                          className="w-full text-xs p-2.5 rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 disabled:opacity-60"
                          rows={2}
                        />

                        {manualReviewError && (
                          <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-[11px] font-semibold text-rose-700 flex items-center gap-1.5">
                            <AlertCircle size={13} className="shrink-0 text-rose-500" />
                            <span>{manualReviewError}</span>
                          </div>
                        )}
                        {manualReviewSuccess && (
                          <div className="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-[11px] font-semibold text-emerald-800 flex items-center gap-1.5">
                            <CheckCircle2 size={13} className="shrink-0 text-emerald-500" />
                            <span>{manualReviewSuccess}</span>
                          </div>
                        )}

                        <div className="flex items-center gap-2 pt-1">
                          <button
                            type="button"
                            disabled={isSubmittingReview}
                            onClick={() => void handleManualReviewAction('APPROVE')}
                            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-colors cursor-pointer disabled:cursor-not-allowed shadow-xs"
                          >
                            {isSubmittingReview ? (
                              <>
                                <Loader2 size={12} className="animate-spin" />
                                <span>Submitting…</span>
                              </>
                            ) : (
                              <>
                                <CheckCircle2 size={13} />
                                <span>Approve Document (VERIFIED)</span>
                              </>
                            )}
                          </button>
                          <button
                            type="button"
                            disabled={isSubmittingReview}
                            onClick={() => void handleManualReviewAction('REJECT')}
                            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-colors cursor-pointer disabled:cursor-not-allowed shadow-xs"
                          >
                            {isSubmittingReview ? (
                              <>
                                <Loader2 size={12} className="animate-spin" />
                                <span>Submitting…</span>
                              </>
                            ) : (
                              <>
                                <XCircle size={13} />
                                <span>Reject Document</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    ) : getDocVerificationStatus(selectedDocId) === 'VERIFIED' ? (
                      <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
                        <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
                        <div>
                          <p className="font-bold">Document Identity Verified</p>
                          <p className="text-[11px] text-emerald-700 mt-0.5">
                            This document has persisting status VERIFIED and is eligible to proceed to scoring and ranking.
                          </p>
                        </div>
                      </div>
                    ) : getDocVerificationStatus(selectedDocId) === 'REJECTED' ? (
                      <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center gap-2">
                        <XCircle size={16} className="text-rose-600 shrink-0" />
                        <div>
                          <p className="font-bold">Document Identity Rejected</p>
                          <p className="text-[11px] text-rose-700 mt-0.5">
                            This document was manually rejected and is blocked from scoring, ranking, and shortlisting.
                          </p>
                        </div>
                      </div>
                    ) : getDocVerificationStatus(selectedDocId) === 'FAILED' ? (
                      <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center gap-2">
                        <XCircle size={16} className="text-rose-600 shrink-0" />
                        <div>
                          <p className="font-bold">Verification Failed</p>
                          <p className="text-[11px] text-rose-700 mt-0.5">
                            System processing error occurred. Use Retry Failed Verification or re-upload the resume.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="p-3 rounded-lg bg-slate-100 border border-slate-200 text-xs text-slate-700 flex items-center gap-2">
                        <Clock size={16} className="text-slate-400 shrink-0" />
                        <div>
                          <p className="font-bold">Verification Pending</p>
                          <p className="text-[11px] text-slate-500 mt-0.5">
                            This document has not been verified yet. Run initial verification to establish candidate identity.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
