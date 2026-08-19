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
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

export default function Shortlist() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { state, dispatch } = usePipeline()

  const activeDept = DEPARTMENTS.find((d) => d.id === state.activeDepartmentId) || DEPARTMENTS[0]
  const reqTitle = state.selectedProject?.title || 'Requisition'

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
    if (selectedForAssessment.length === 0) {
      alert('Please select at least one candidate to send to assessment.')
      return
    }
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
      alert('Requisition reference (req_ref) not found for this project. Cannot initiate assessment handoff.')
      return
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

      } catch (err) {
        console.warn('Backend handoff warning:', err)
      }
    }


    dispatch({
      type: 'SEND_TO_ASSESSMENT',
      payload: { candidateIds: selectedForAssessment, reqRef, linksMap },
    })
    navigate(`/projects/${projectId}/assessment`)
  }


  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Navigation Breadcrumb */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
          <button
            type="button"
            onClick={() => navigate(`/departments/${activeDept.id}`)}
            className="hover:text-blue-600 transition-colors"
          >
            {activeDept.name}
          </button>
          <span>/</span>
          <button
            type="button"
            onClick={() => navigate(`/projects/${projectId}/rankings`)}
            className="hover:text-blue-600 transition-colors"
          >
            Rankings
          </button>
          <span>/</span>
          <span className="text-slate-900 font-bold">Shortlisted Talent</span>
        </div>

        <button
          type="button"
          onClick={() => navigate(`/projects/${projectId}/rankings`)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
        >
          <ListOrdered size={15} />
          Back to Candidate Rankings
        </button>
      </div>

      {/* Header Banner */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold mb-2 border border-emerald-100">
            <UserCheck size={13} />
            Shortlist Handoff Management
          </div>
          <h1 className="text-xl font-extrabold text-slate-900">
            Shortlisted Talent Pool
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Review top evaluated candidates for <span className="font-semibold text-slate-900">{reqTitle}</span> and dispatch to technical assessments.
          </p>
        </div>

        {/* Primary Action Button */}
        <button
          type="button"
          onClick={handleSendToAssessment}
          disabled={selectedForAssessment.length === 0}
          className="inline-flex items-center gap-2.5 px-6 py-3 bg-emerald-600 text-white rounded-xl text-xs font-extrabold hover:bg-emerald-700 disabled:opacity-50 transition-colors shadow-md self-stretch md:self-auto justify-center"
        >
          <Send size={15} />
          Send Selected ({selectedForAssessment.length}) to Assessment
        </button>
      </div>

      {/* Candidates List / Table */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm space-y-4">
        {/* Controls Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-700">
              Shortlisted ({shortlistedCandidates.length})
            </span>
            <div className="h-4 w-[1px] bg-slate-200" />
            <button
              type="button"
              onClick={handleSelectAll}
              className="text-xs text-blue-600 font-semibold hover:underline"
            >
              Select All
            </button>
            <button
              type="button"
              onClick={handleDeselectAll}
              className="text-xs text-slate-500 font-semibold hover:underline"
            >
              Deselect All
            </button>
          </div>

          <span className="text-xs text-slate-500 font-medium">
            <span className="font-bold text-slate-900">{selectedForAssessment.length}</span> of {shortlistedCandidates.length} ready for assessment
          </span>
        </div>

        {shortlistedCandidates.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-400">
            No candidates shortlisted yet. Go to Candidate Rankings to shortlist candidates.
          </div>
        ) : (
          <div className="overflow-x-auto border border-slate-100 rounded-xl">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 text-[11px] font-bold text-slate-400 uppercase border-b border-slate-100">
                  <th className="py-3 px-4 w-12 text-center">Select</th>
                  <th className="py-3 px-4">Candidate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {shortlistedCandidates.map((c) => {
                  const isChecked = selectedForAssessment.includes(c.id)
                  return (
                    <tr key={c.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-4 text-center">
                        <button
                          type="button"
                          onClick={() => toggleSelect(c.id)}
                          className="text-slate-400 hover:text-blue-600"
                        >
                          {isChecked ? (
                            <CheckSquare size={18} className="text-blue-600" />
                          ) : (
                            <Square size={18} />
                          )}
                        </button>
                      </td>
                      <td className="py-3.5 px-4">
                        <p className="font-bold text-slate-900">{c.name}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">{c.email}</p>
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
