import { useEffect, useRef, useState } from 'react'
import { FolderPlus, Briefcase, Trash2, Search, SlidersHorizontal } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Project } from '@/api'
import { usePipeline } from '@/store/pipelineStore'
import { EmptyState, PageHeader, Skeleton, StatusBadge } from '@/components/ui/SaaS'

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [sort, setSort] = useState('updated')
  const loadedRef = useRef(false)
  const navigate = useNavigate()
  const { state, dispatch, startNewScreening } = usePipeline()

  useEffect(() => {
    if (loadedRef.current) return
    loadedRef.current = true
    api.listProjects()
      .then(({ items }) => {
        setProjects(items)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to list projects.'))
      .finally(() => setLoading(false))
  }, [])

  const open = (project: Project) => {
    dispatch({ type: 'SELECT_PROJECT', payload: project })
    navigate(`/projects/${project.id}/overview`)
  }

  const remove = async (project: Project) => {
    if (!window.confirm(`Delete "${project.title}"? Existing project data will no longer be available in the application.`)) return
    setDeletingId(project.id)
    setError(null)
    try {
      await api.deleteProject(project.id)
      setProjects((current) => current.filter((item) => item.id !== project.id))
      if (state.projectId === project.id) startNewScreening()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Unable to delete project.')
    } finally {
      setDeletingId(null)
    }
  }

  const visibleProjects = projects
    .filter((project) => (statusFilter === 'ALL' || project.status === statusFilter) && `${project.title} ${project.target_role} ${project.department ?? ''}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a,b) => sort === 'name' ? a.title.localeCompare(b.title) : new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())

  return <div className="max-w-5xl mx-auto">
    <PageHeader title="Projects" description="Create and manage your screening projects." action={<button className="btn-primary" onClick={() => navigate('/projects/new')}><FolderPlus size={15}/> New Project</button>}/>
    <div className="flex flex-col md:flex-row gap-3 mb-7">
      <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-lg px-3 flex-1"><Search size={15} className="text-slate-400"/><input value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Search projects" className="border-0 py-2.5 flex-1 outline-none text-[13px]"/></div>
      <select value={statusFilter} onChange={(e)=>setStatusFilter(e.target.value)} className="bg-white px-3 py-2 text-[12px]"><option value="ALL">All statuses</option><option>DRAFT</option><option>ACTIVE</option><option>COMPLETED</option><option>ARCHIVED</option></select>
      <select value={sort} onChange={(e)=>setSort(e.target.value)} className="bg-white px-3 py-2 text-[12px]"><option value="updated">Recently updated</option><option value="name">Project name</option></select>
      <SlidersHorizontal size={15} className="hidden"/>
    </div>
    {error && <p className="card p-4 text-red-500">{error}</p>}
    {loading ? <div className="grid md:grid-cols-2 gap-5"><Skeleton/><Skeleton/><Skeleton/></div> : projects.length === 0 ?
      <EmptyState icon={Briefcase} title="No projects yet" description="Create your first screening project to begin." action={<button className="btn-primary" onClick={()=>navigate('/projects/new')}>Create Project</button>}/> :
      <div className="grid md:grid-cols-2 gap-5">{visibleProjects.map((project) => <div className="card p-6" key={project.id}>
        <div className="flex justify-between gap-4"><div><h2 className="text-[16px] font-semibold text-slate-900">{project.title}</h2><p className="text-[12px] text-slate-500 mt-1">{project.target_role}{project.department ? ` · ${project.department}` : ''}</p></div><StatusBadge tone={project.status==='ACTIVE'?'success':'neutral'}>{project.status}</StatusBadge></div>
        <div className="my-6 grid grid-cols-2 gap-4 text-[11px] text-slate-500"><span><strong className="mb-1 block text-[13px] text-slate-800">{project.department || 'Not specified'}</strong>Department</span><span><strong className="mb-1 block text-[13px] text-slate-800">{new Date(project.created_at).toLocaleDateString()}</strong>Created</span></div>
        <p className="text-[11px] text-slate-400 mb-4">Updated {new Date(project.updated_at).toLocaleString()} · Open the project to view live pipeline totals.</p>
        <div className="flex gap-2">
          <button className="btn-outline flex-1 justify-center" onClick={() => open(project)}>Open Project</button>
          <button type="button" disabled={deletingId === project.id} onClick={() => void remove(project)} className="px-3 py-2 rounded-lg border border-red-200 text-red-500 hover:bg-red-50 disabled:opacity-50" title="Delete project"><Trash2 size={14}/></button>
        </div>
      </div>)}</div>}
  </div>
}
