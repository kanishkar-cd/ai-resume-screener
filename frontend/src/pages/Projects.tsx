import { useEffect, useState } from 'react'
import { FolderPlus, Briefcase, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Project } from '@/api'
import { usePipeline } from '@/store/pipelineStore'

type ProjectStats = { resumes: number; jd: string; candidates: number }

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [stats, setStats] = useState<Record<string, ProjectStats>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const navigate = useNavigate()
  const { state, dispatch, startNewScreening } = usePipeline()

  useEffect(() => {
    api.listProjects()
      .then(async ({ items }) => {
        setProjects(items)
        const entries = await Promise.all(items.map(async (project) => {
          const [resumes, jd, scores] = await Promise.all([
            api.listProjectResumes(project.id).catch(() => null),
            api.getJobDescription(project.id).catch(() => null),
            api.getProjectScores(project.id).catch(() => []),
          ])
          return [project.id, {
            resumes: resumes?.total ?? 0,
            jd: jd ? 'Uploaded' : 'Not uploaded',
            candidates: scores.length,
          }] as const
        }))
        setStats(Object.fromEntries(entries))
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to list projects.'))
      .finally(() => setLoading(false))
  }, [])

  const open = (project: Project) => {
    dispatch({ type: 'SELECT_PROJECT', payload: project })
    navigate(`/projects/${project.id}`)
  }

  const remove = async (project: Project) => {
    if (!window.confirm(`Delete "${project.title}"? Existing project data will no longer be available in the application.`)) return
    setDeletingId(project.id)
    setError(null)
    try {
      await api.deleteProject(project.id)
      setProjects((current) => current.filter((item) => item.id !== project.id))
      setStats((current) => {
        const { [project.id]: _removed, ...rest } = current
        return rest
      })
      if (state.projectId === project.id) startNewScreening()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Unable to delete project.')
    } finally {
      setDeletingId(null)
    }
  }

  return <div className="max-w-5xl mx-auto">
    <div className="flex justify-between items-center mb-5">
      <div><h1 className="text-[26px] font-bold text-slate-800">Projects</h1><p className="text-[13px] text-slate-500">Each project contains one isolated screening workflow.</p></div>
      <button className="btn-primary" onClick={() => navigate('/projects/new')}><FolderPlus size={15}/> Create Project</button>
    </div>
    {error && <p className="card p-4 text-red-500">{error}</p>}
    {loading ? <div className="card p-8 text-center text-slate-400">Loading projects…</div> : projects.length === 0 ?
      <div className="card p-10 text-center"><Briefcase className="mx-auto text-slate-300 mb-3"/><p className="font-semibold text-slate-700">No projects yet</p><p className="text-[12px] text-slate-400 mt-1">Create your first screening project.</p></div> :
      <div className="grid md:grid-cols-2 gap-4">{projects.map((project) => <div className="card p-5" key={project.id}>
        <div className="flex justify-between"><h2 className="font-bold text-slate-800">{project.title}</h2><span className="text-[10px] font-bold text-sky-700 bg-sky-50 px-2 py-1 rounded">{project.status}</span></div>
        <p className="text-[12px] text-slate-600 mt-2">{project.target_role}</p><p className="text-[11px] text-slate-400">{project.department || 'No department'}</p>
        <div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500 my-4"><span>Resumes: {stats[project.id]?.resumes ?? 0}</span><span>JD: {stats[project.id]?.jd ?? 'Checking…'}</span><span>Candidates: {stats[project.id]?.candidates ?? 0}</span></div>
        <p className="text-[11px] text-slate-400 mb-4">Updated {new Date(project.updated_at).toLocaleString()}</p>
        <div className="flex gap-2">
          <button className="btn-outline flex-1 justify-center" onClick={() => open(project)}>Open Project</button>
          <button type="button" disabled={deletingId === project.id} onClick={() => void remove(project)} className="px-3 py-2 rounded-lg border border-red-200 text-red-500 hover:bg-red-50 disabled:opacity-50" title="Delete project"><Trash2 size={14}/></button>
        </div>
      </div>)}</div>}
  </div>
}
