import { useParams } from 'react-router-dom'
import { usePipeline } from '@/store/pipelineStore'
import CandidateVerificationDashboard from '@/components/verification/CandidateVerificationDashboard'

export default function VerificationPage() {
  const { state } = usePipeline()
  const { projectId: routeProjectId } = useParams<{ projectId: string }>()
  const projectId = routeProjectId || state.projectId

  if (!projectId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] text-center p-8">
        <h3 className="text-sm font-bold text-slate-700">No Project Selected</h3>
        <p className="text-xs text-slate-500 mt-1">Please select a job opening to view candidate verification.</p>
      </div>
    )
  }

  const jobOpeningId =
    (state.selectedProject?.metadata_json as Record<string, any> | undefined)?.zoho_job_opening_id ||
    (state.selectedProject?.metadata_json as Record<string, any> | undefined)?.job_opening_id

  return (
    <CandidateVerificationDashboard
      projectId={projectId}
      jobOpeningId={jobOpeningId ? String(jobOpeningId) : undefined}
    />
  )
}
