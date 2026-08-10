import { ArrowLeft, Pencil } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

const tabs = [
  ['Overview', ''], ['Job Description', 'job-description'], ['Resumes', 'resumes'],
  ['Weightage', 'weightage'], ['Processing', 'processing'], ['Candidates', 'candidates'],
  ['Rankings', 'rankings'], ['Reports', 'reports'],
]

export default function ProjectHeader() {
  const { state, dispatch } = usePipeline()
  const navigate = useNavigate()
  const location = useLocation()
  const project = state.selectedProject
  if (!project || !location.pathname.startsWith(`/projects/${project.id}`)) return null
  const root = `/projects/${project.id}`
  const editProject = async () => {
    const title = window.prompt('Project name', project.title)?.trim()
    if (!title || title === project.title) return
    const updated = await api.updateProject(project.id, { title })
    dispatch({ type: 'SELECT_PROJECT', payload: updated })
  }
  return (
    <div className="card p-5 mb-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-slate-800">{project.title}</h1>
          <p className="text-[12px] text-slate-500 mt-1">{project.target_role}{project.department ? ` · ${project.department}` : ''}</p>
          <span className="inline-flex mt-2 px-2 py-1 rounded-md bg-sky-50 text-sky-700 text-[10px] font-bold">{project.status}</span>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => navigate('/projects')} className="btn-outline text-[12px] px-3 py-2"><ArrowLeft size={13}/> Back to Projects</button>
          <button type="button" onClick={() => void editProject()} className="btn-outline text-[12px] px-3 py-2"><Pencil size={13}/> Edit Project</button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mt-5 pt-4 border-t border-slate-100">
        {tabs.map(([label, suffix]) => {
          const path = suffix ? `${root}/${suffix}` : root
          const active = location.pathname === path
          return <button type="button" key={label} onClick={() => navigate(path)} className={`px-3 py-2 rounded-lg text-[11px] font-semibold ${active ? 'bg-sky-600 text-white' : 'text-slate-500 hover:bg-sky-50 hover:text-sky-700'}`}>{label}</button>
        })}
      </div>
    </div>
  )
}
