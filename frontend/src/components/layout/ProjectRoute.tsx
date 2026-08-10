import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { api, ApiError } from '@/api'
import { usePipeline } from '@/store/pipelineStore'

export default function ProjectRoute({ children }: { children: ReactNode }) {
  const { projectId } = useParams()
  const { state, dispatch } = usePipeline()
  const [loading, setLoading] = useState(state.projectId !== projectId || !state.selectedProject)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    if (state.projectId === projectId && state.selectedProject) {
      setLoading(false)
      return
    }
    let active = true
    setLoading(true)
    api.getProject(projectId)
      .then((project) => {
        if (active) dispatch({ type: 'SELECT_PROJECT', payload: project })
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : 'Unable to open project.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [dispatch, projectId, state.projectId, state.selectedProject])

  if (!projectId) return <Navigate to="/projects" replace />
  if (loading) return <div className="card p-8 text-center text-slate-500">Loading project…</div>
  if (error) return <div className="card p-8 text-center text-red-500">{error}</div>
  return <>{children}</>
}
