import { Pencil } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { usePipeline } from '@/store/pipelineStore'
import { api } from '@/api'

const tabs = [
  ['Candidates', 'candidates'],
  ['Rankings', 'rankings'],
  ['Reports', 'reports'],
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
    <div className="mb-8 border-b border-slate-200 bg-white px-6 py-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-slate-900">{project.title}</h1>
          <p className="text-[12px] text-slate-500 mt-1">
            {project.target_role}
            {project.department ? ` · ${project.department}` : ''}
          </p>
          <span className="inline-flex mt-2 px-2 py-1 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-bold capitalize">
            {project.status}
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void editProject()}
            className="btn-outline text-[12px] px-3 py-2 cursor-pointer"
          >
            <Pencil size={13} /> Edit Project
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mt-5 -mb-5">
        {tabs.map(([label, suffix]) => {
          const path = `${root}/${suffix}`
          const active =
            location.pathname === path ||
            (suffix === 'rankings' &&
              (location.pathname === root || location.pathname === `${root}/overview`))
          return (
            <button
              type="button"
              key={label}
              onClick={() => navigate(path)}
              className={`border-b-2 px-3 py-3 text-[11px] font-semibold cursor-pointer ${active
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-slate-500 hover:text-slate-900'
                }`}
            >
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
