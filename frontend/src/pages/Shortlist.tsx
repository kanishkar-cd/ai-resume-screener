import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  UserCheck,
  Send,
  Building2,
  CheckCircle2,
  ListOrdered,
  Search,
  CheckSquare,
  Square,
  Award,
  ArrowRight,
  Loader2,
  AlertTriangle,
  ShieldAlert,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, ApiError } from '@/api'

export default function Shortlist() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state, dispatch } = usePipeline()
  const [isSending, setIsSending] = useState(false)
  const [handoffError, setHandoffError] = useState<string | null>(null)
  const [verifiedDocIds, setVerifiedDocIds] = useState<Set<string>>(new Set())
  const [loadedVerification, setLoadedVerification] = useState(false)

  // Filter candidates who are currently shortlisted ('screened')
  const shortlistedCandidates = state.candidates.filter((c) => c.status === 'screened')

  // Load backend document verification status to determine eligibility
  useEffect(() => {
    if (!projectId) return
    let active = true
    void api
      .listProjectResumes(projectId)
      .then((res) => {
        if (!active) return
        const set = new Set<string>()
        for (const doc of res.items || []) {
          const status = (doc.metadata_json as Record<string, any> | undefined)?.verification?.verification_status
          if (status === 'VERIFIED') {
            set.add(doc.id)
          }
        }
        setVerifiedDocIds(set)
        setLoadedVerification(true)
      })
      .catch(() => {
        if (active) setLoadedVerification(true)
      })
    return () => {
      active = false
    }
  }, [projectId])

  const [selectedForAssessment, setSelectedForAssessment] = useState<string[]>([])

  // Initialize selected candidates, selecting only verified candidates
  useEffect(() => {
    if (!loadedVerification) {
      setSelectedForAssessment(shortlistedCandidates.map((c) => c.id))
    } else {
      setSelectedForAssessment(
        shortlistedCandidates
          .filter((c) => verifiedDocIds.has(c.id))
          .map((c) => c.id),
      )
    }
  }, [shortlistedCandidates, loadedVerification, verifiedDocIds])

  const toggleSelect = (id: string) => {
    if (loadedVerification && !verifiedDocIds.has(id)) return
    setSelectedForAssessment((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    )
  }

  const handleSelectAll = () => {
    const eligible = loadedVerification
      ? shortlistedCandidates.filter((c) => verifiedDocIds.has(c.id)).map((c) => c.id)
      : shortlistedCandidates.map((c) => c.id)
    setSelectedForAssessment(eligible)
  }

  const handleDeselectAll = () => {
    setSelectedForAssessment([])
  }

  const handleSendToAssessment = async () => {
    if (selectedForAssessment.length === 0 || isSending) {
      return
    }

    setHandoffError(null)

    // Check if any selected candidate is unverified (Phase 3 Progression UX check)
    if (loadedVerification) {
      const ineligible = selectedForAssessment.filter((id) => !verifiedDocIds.has(id))
      if (ineligible.length > 0) {
        setHandoffError(
          `${ineligible.length} candidate(s) have unverified identity. Only candidates with persisted VERIFIED status can be handed off for assessment.`,
        )
        return
      }
    }

    setIsSending(true)
    try {
      let reqRef = (state.selectedProject?.metadata_json as Record<string, any> | undefined)?.req_ref as string | undefined
      if (!reqRef && projectId) {
        try {
          const proj = await api.getProject(projectId)
          reqRef = (proj.metadata_json as Record<string, any> | undefined)?.req_ref as string | undefined
        } catch (err) {
          console.warn('Failed to fetch project details for requisition reference:', err)
        }
      }

      if (!reqRef || !reqRef.trim()) {
        reqRef = projectId ? `REQ-${projectId}` : 'REQ-DEFAULT'
      }

      const linksMap: Record<string, string | null> = {}

      if (projectId) {
        const response = await api.handoffAssessment(projectId, selectedForAssessment, reqRef)
        if (response?.candidates) {
          for (const item of response.candidates) {
            linksMap[item.candidate_id] = item.assessment_link
          }
        }
      }

      dispatch({
        type: 'SEND_TO_ASSESSMENT',
        payload: { candidateIds: selectedForAssessment, reqRef, linksMap },
      })
      navigate(`/projects/${projectId}/assessment`)
    } catch (err: any) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err?.message || 'Assessment handoff encountered an issue. Please try again.'
      setHandoffError(msg)
    } finally {
      setIsSending(false)
    }
  }

  const countText = `${selectedForAssessment.length} ${
    selectedForAssessment.length === 1 ? 'candidate' : 'candidates'
  } selected`


  return (
    <div className="w-full max-w-5xl mx-auto space-y-5 pb-6">
      {/* ── Page Header & Direct Action ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">
              Shortlisted Candidates
            </h1>
            <span className="text-xs font-bold text-slate-600 bg-slate-100 border border-slate-200/80 px-2.5 py-0.5 rounded-full">
              {shortlistedCandidates.length}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1 max-w-xl leading-relaxed">
            Select candidates to dispatch for technical assessment.
          </p>
        </div>

        {/* Primary Action Button */}
        <div>
          <button
            type="button"
            onClick={() => void handleSendToAssessment()}
            disabled={selectedForAssessment.length === 0 || isSending}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm cursor-pointer disabled:cursor-not-allowed"
          >
            {isSending ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                <span>Sending to Assessment…</span>
              </>
            ) : (
              <>
                <Send size={14} />
                <span>Send Selected to Assessment</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Progression UX Error Banner ── */}
      {handoffError && (
        <div className="p-4 rounded-xl border border-rose-200 bg-rose-50/90 text-xs text-rose-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={16} className="text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-rose-900">Assessment Handoff Blocked</p>
              <p className="mt-0.5 leading-relaxed">{handoffError}</p>
            </div>
          </div>
          {projectId && (
            <button
              type="button"
              onClick={() => navigate(`/projects/${projectId}/verification`)}
              className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg text-xs font-bold transition-colors shrink-0 shadow-2xs cursor-pointer"
            >
              Go to Candidate Verification →
            </button>
          )}
        </div>
      )}

      {/* ── Candidates Selection Card ── */}
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-xs overflow-hidden">
        {/* Controls Toolbar */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-800">
              {countText}
            </span>
            <div className="h-3.5 w-[1px] bg-slate-200" />
            <button
              type="button"
              onClick={handleSelectAll}
              className="text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
            >
              Select All
            </button>
            <span className="text-slate-300 text-xs">·</span>
            <button
              type="button"
              onClick={handleDeselectAll}
              className="text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
            >
              Deselect All
            </button>
          </div>
        </div>

        {shortlistedCandidates.length === 0 ? (
          <div className="py-16 text-center text-xs text-slate-400">
            <UserCheck size={32} className="mx-auto mb-3 opacity-25" />
            <p className="font-semibold text-slate-700 text-sm">No candidates shortlisted yet</p>
            <p className="mt-1 text-slate-400 text-xs">Go to Candidate Rankings to shortlist candidates for assessment.</p>
            <button
              type="button"
              onClick={() => (projectId ? navigate(`/projects/${projectId}/rankings`) : navigate('/dashboard'))}
              className="mt-4 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-bold transition-colors cursor-pointer"
            >
              Back to Candidate Rankings
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/40 text-left">
                  <th className="px-6 py-3.5 text-[11px] font-bold text-slate-400 uppercase tracking-wider w-16 text-center">Select</th>
                  <th className="px-6 py-3.5 text-[11px] font-bold text-slate-400 uppercase tracking-wider">Candidate</th>
                  <th className="px-6 py-3.5 text-[11px] font-bold text-slate-400 uppercase tracking-wider text-right">Verification Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {shortlistedCandidates.map((c) => {
                  const isVerified = !loadedVerification || verifiedDocIds.has(c.id)
                  const isChecked = selectedForAssessment.includes(c.id)
                  return (
                    <tr
                      key={c.id}
                      onClick={() => isVerified && toggleSelect(c.id)}
                      className={`${isVerified ? 'hover:bg-slate-50/70 cursor-pointer' : 'bg-slate-50/40 opacity-70 cursor-not-allowed'} transition-colors`}
                    >
                      <td className="px-6 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          disabled={!isVerified}
                          onClick={() => isVerified && toggleSelect(c.id)}
                          className={`${isVerified ? 'text-slate-400 hover:text-blue-600 cursor-pointer' : 'text-slate-300 cursor-not-allowed'} transition-colors flex items-center justify-center mx-auto`}
                        >
                          {isChecked ? (
                            <CheckSquare size={19} className="text-blue-600" />
                          ) : (
                            <Square size={19} className="text-slate-300" />
                          )}
                        </button>
                      </td>
                      <td className="px-6 py-3.5">
                        <div className="flex items-center gap-3.5">
                          <div className="w-9 h-9 rounded-full bg-slate-100 border border-slate-200/80 flex items-center justify-center text-slate-700 font-bold text-xs shrink-0 shadow-2xs">
                            {c.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="font-bold text-slate-900 text-sm">{c.name}</p>
                            <p className="text-xs text-slate-500 font-normal mt-0.5">{c.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        {isVerified ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <CheckCircle2 size={11} className="text-emerald-500" />
                            Verified
                          </span>
                        ) : (
                          <span
                            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 text-amber-800 border border-amber-200"
                            title="Candidate must be verified before handoff to technical assessment"
                          >
                            <AlertTriangle size={11} className="text-amber-600" />
                            Unverified (Blocked)
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
