import { useState } from 'react'
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
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

export default function Shortlist() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state, dispatch } = usePipeline()
  const [isSending, setIsSending] = useState(false)

  // Filter candidates who are currently shortlisted ('screened')
  const shortlistedCandidates = state.candidates.filter((c) => c.status === 'screened')

  const [selectedForAssessment, setSelectedForAssessment] = useState<string[]>(
    shortlistedCandidates.map((c) => c.id)
  )

  const toggleSelect = (id: string) => {
    setSelectedForAssessment((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    )
  }

  const handleSelectAll = () => {
    setSelectedForAssessment(shortlistedCandidates.map((c) => c.id))
  }

  const handleDeselectAll = () => {
    setSelectedForAssessment([])
  }

  const handleSendToAssessment = async () => {
    if (selectedForAssessment.length === 0 || isSending) {
      return
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
        try {
          const response = await api.handoffAssessment(projectId, selectedForAssessment, reqRef)
          if (response?.candidates) {
            for (const item of response.candidates) {
              linksMap[item.candidate_id] = item.assessment_link
            }
          }
        } catch (err: any) {
          console.error('Backend handoff error:', err)
        }
      }

      dispatch({
        type: 'SEND_TO_ASSESSMENT',
        payload: { candidateIds: selectedForAssessment, reqRef, linksMap },
      })
      navigate(`/projects/${projectId}/assessment`)
    } catch (err: any) {
      alert(err?.message || 'Assessment handoff encountered an issue. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  const countText = `${selectedForAssessment.length} ${
    selectedForAssessment.length === 1 ? 'candidate' : 'candidates'
  } selected`

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6 pb-10">
      {/* ── Page Header & Direct Action ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Shortlisted Candidates</h1>
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

      {/* ── Candidates Selection Card ── */}
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-xs overflow-hidden">
        {/* Controls Toolbar */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-800">
              {countText}
            </span>
            <div className="h-4 w-[1px] bg-slate-200" />
            <button
              type="button"
              onClick={handleSelectAll}
              className="text-xs text-blue-600 font-semibold hover:underline cursor-pointer"
            >
              Select All
            </button>
            <button
              type="button"
              onClick={handleDeselectAll}
              className="text-xs text-slate-500 font-semibold hover:underline cursor-pointer"
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
              onClick={() => projectId ? navigate(`/projects/${projectId}/rankings`) : navigate('/dashboard')}
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
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {shortlistedCandidates.map((c) => {
                  const isChecked = selectedForAssessment.includes(c.id)
                  return (
                    <tr
                      key={c.id}
                      onClick={() => toggleSelect(c.id)}
                      className="hover:bg-slate-50/70 transition-colors cursor-pointer"
                    >
                      <td className="px-6 py-4 text-center" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => toggleSelect(c.id)}
                          className="text-slate-400 hover:text-blue-600 transition-colors cursor-pointer flex items-center justify-center mx-auto"
                        >
                          {isChecked ? (
                            <CheckSquare size={18} className="text-blue-600" />
                          ) : (
                            <Square size={18} className="text-slate-300 hover:text-slate-400" />
                          )}
                        </button>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3.5">
                          <div className="w-10 h-10 rounded-full bg-slate-100 border border-slate-200/80 flex items-center justify-center text-slate-700 font-bold text-xs shrink-0 shadow-2xs">
                            {c.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="font-bold text-slate-900 text-sm">{c.name}</p>
                            <p className="text-xs text-slate-500 font-normal mt-0.5">{c.email}</p>
                          </div>
                        </div>
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
