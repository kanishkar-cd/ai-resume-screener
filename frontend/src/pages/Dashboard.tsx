import { useEffect, useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderKanban,
  Building2,
  AlertCircle,
  Plus,
  ChevronRight,
  Search,
  Briefcase,
  Trash2,
  Loader2,
  X,
  ArrowRight,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, Project } from '@/api'

function getExperienceLevel(proj: Project): 'Fresher' | 'Experienced' {
  if (proj.metadata_json && typeof proj.metadata_json.experience_level === 'string') {
    const level = proj.metadata_json.experience_level.toLowerCase()
    if (level.includes('experienced')) return 'Experienced'
    if (level.includes('fresher')) return 'Fresher'
  }
  if (proj.description) {
    const desc = proj.description.toLowerCase()
    if (desc.includes('experienced')) return 'Experienced'
    if (desc.includes('fresher')) return 'Fresher'
  }
  if (proj.title) {
    const title = proj.title.toLowerCase()
    if (title.includes('experienced')) return 'Experienced'
    if (title.includes('fresher')) return 'Fresher'
  }
  return 'Fresher'
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { dispatch } = usePipeline()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')

  // Delete state
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteProject, setConfirmDeleteProject] = useState<Project | null>(null)
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const fetchProjects = useCallback(() => {
    setLoading(true)
    api.listProjects()
      .then((res) => {
        setProjects(res.items || [])
        setError(null)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Unable to connect to backend service')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const handleSelectDepartmentClick = () => {
    dispatch({ type: 'SET_DEPARTMENT_ID', payload: null as any })
    navigate('/departments')
  }

  const handleRequisitionClick = (proj: Project) => {
    const dept = DEPARTMENTS.find((d) => d.name === proj.department)
    if (dept) {
      dispatch({ type: 'SET_DEPARTMENT_ID', payload: dept.id })
    }
    dispatch({
      type: 'SELECT_PROJECT',
      payload: {
        id: proj.id,
        title: proj.title,
        target_role: proj.target_role,
        department: proj.department,
        description: proj.description,
        status: proj.status,
        created_at: proj.created_at,
        updated_at: proj.updated_at,
      },
    })
    navigate(`/projects/${proj.id}/rankings`)
  }

  const handleDeleteClick = (e: React.MouseEvent, proj: Project) => {
    e.stopPropagation()
    setDeleteError(null)
    setConfirmDeleteProject(proj)
  }

  const handleDeleteAllClick = () => {
    setDeleteError(null)
    setConfirmDeleteAll(true)
  }

  const handleConfirmDelete = async () => {
    if (!confirmDeleteProject) return
    const targetId = confirmDeleteProject.id
    setDeletingId(targetId)
    setDeleteError(null)
    try {
      await api.deleteProject(targetId)
      setProjects((prev) => prev.filter((p) => p.id !== targetId))
      setConfirmDeleteProject(null)
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete requisition. Please try again.')
    } finally {
      setDeletingId(null)
    }
  }

  const handleConfirmDeleteAll = async () => {
    if (projects.length === 0) return
    setIsDeletingAll(true)
    setDeleteError(null)
    try {
      await Promise.all(projects.map((p) => api.deleteProject(p.id)))
      setProjects([])
      setConfirmDeleteAll(false)
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete all requisitions. Please try again.')
    } finally {
      setIsDeletingAll(false)
    }
  }

  const filteredProjects = useMemo(() => {
    return projects.filter(
      (p) =>
        p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (p.department && p.department.toLowerCase().includes(searchTerm.toLowerCase())) ||
        (p.target_role && p.target_role.toLowerCase().includes(searchTerm.toLowerCase()))
    )
  }, [projects, searchTerm])

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-7">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200/60 pb-6">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 mb-1">
            <Briefcase size={13} className="text-blue-600" />
            <span className="text-slate-700 font-bold">Recruiter Portal</span>
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2.5">
            Recruiter Dashboard
          </h1>
        </div>

        {/* Precise Compact Select Department CTA */}
        <button
          type="button"
          onClick={handleSelectDepartmentClick}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-xs hover:shadow-md transition-all cursor-pointer self-start md:self-auto"
        >
          <Building2 size={15} />
          <span>Select Department</span>
          <ArrowRight size={14} />
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50/80 border border-red-200/80 rounded-2xl flex items-center gap-3 text-red-700 text-xs font-semibold shadow-xs">
          <AlertCircle size={16} className="shrink-0" />
          <div>
            <p className="font-bold">Backend Service Error</p>
            <p className="text-[11px] font-normal text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Modern KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        {/* Active Requisitions */}
        <div className="group bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs hover:shadow-md hover:border-blue-200 transition-all flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Active Requisitions</p>
            <div className="flex items-baseline gap-2 mt-1">
              <p className="text-2.5xl font-extrabold text-slate-900">{loading ? '...' : projects.length}</p>
              <span className="text-[11px] text-slate-400 font-medium">campaigns</span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-blue-50/80 group-hover:bg-blue-600 text-blue-600 group-hover:text-white flex items-center justify-center transition-colors">
            <FolderKanban size={20} />
          </div>
        </div>

        {/* Company Departments */}
        <div className="group bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs hover:shadow-md hover:border-blue-200 transition-all flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Company Departments</p>
            <div className="flex items-baseline gap-2 mt-1">
              <p className="text-2.5xl font-extrabold text-slate-900">{DEPARTMENTS.length}</p>
              <span className="text-[11px] text-slate-400 font-medium">active units</span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-indigo-50/80 group-hover:bg-indigo-600 text-indigo-600 group-hover:text-white flex items-center justify-center transition-colors">
            <Building2 size={20} />
          </div>
        </div>
      </div>

      {/* Active Requisitions Table Section */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs space-y-4">
        {/* Table Header & Search */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold text-slate-900 tracking-tight">Active Requisitions</h2>
            {!loading && !error && (
              <span className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-bold border border-blue-100/80">
                {filteredProjects.length} {filteredProjects.length === 1 ? 'requisition' : 'requisitions'}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="relative max-w-xs w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filter by title, department, or role..."
                className="w-full pl-8 pr-3.5 py-1.5 bg-slate-50 border border-slate-200/80 rounded-xl text-xs font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 placeholder:text-slate-400 transition-all"
              />
            </div>

            {projects.length > 0 && (
              <button
                type="button"
                onClick={handleDeleteAllClick}
                disabled={isDeletingAll}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100/80 border border-red-200/80 rounded-xl transition-all cursor-pointer shrink-0 disabled:opacity-50"
              >
                <Trash2 size={14} className="shrink-0" />
                <span>Delete All</span>
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="py-16 text-center text-xs text-slate-400 font-medium flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin text-blue-600" />
            <span>Loading active requisitions from database...</span>
          </div>
        ) : filteredProjects.length === 0 ? (
          <div className="py-16 text-center space-y-3">
            <FolderKanban size={32} className="mx-auto text-slate-300" />
            <p className="text-sm font-semibold text-slate-700">No requisitions found</p>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              {searchTerm ? 'No requisitions match your filter criteria.' : 'No active requisitions created yet.'}
            </p>
            {!searchTerm && (
              <button
                type="button"
                onClick={handleSelectDepartmentClick}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold transition-all shadow-xs"
              >
                <Building2 size={15} />
                <span>Select Department & Launch</span>
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto border border-slate-100/90 rounded-xl">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <th className="py-3 px-4.5">Title</th>
                  <th className="py-3 px-4">Department</th>
                  <th className="py-3 px-4">Target Role</th>
                  <th className="py-3 px-4 text-center">Level</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {filteredProjects.map((proj) => (
                  <tr
                    key={proj.id}
                    onClick={() => handleRequisitionClick(proj)}
                    className="hover:bg-blue-50/30 cursor-pointer transition-colors group"
                  >
                    <td className="py-3.5 px-4.5 font-bold text-slate-900">
                      <p className="group-hover:text-blue-600 transition-colors line-clamp-1">{proj.title}</p>
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-block px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-600 text-[10px] font-bold font-mono tracking-tight">
                        {proj.department || 'General'}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-slate-700 font-semibold">{proj.target_role || '—'}</td>
                    <td className="py-3.5 px-4 text-center">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                          getExperienceLevel(proj) === 'Fresher'
                            ? 'bg-blue-50 text-blue-700 border-blue-200/70'
                            : 'bg-indigo-50 text-indigo-700 border-indigo-200/70'
                        }`}
                      >
                        {getExperienceLevel(proj)}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200/60">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        {proj.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-4.5 text-right shrink-0">
                      <div className="inline-flex items-center justify-end gap-2 shrink-0 min-w-[150px]" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => handleRequisitionClick(proj)}
                          className="text-blue-600 hover:text-blue-800 font-semibold text-xs inline-flex items-center gap-1 group-hover:translate-x-0.5 transition-transform whitespace-nowrap"
                        >
                          <span>View Requisition</span>
                          <ChevronRight size={13} />
                        </button>
                        <button
                          type="button"
                          title="Delete Requisition"
                          onClick={(e) => handleDeleteClick(e, proj)}
                          disabled={deletingId === proj.id}
                          className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors cursor-pointer shrink-0 disabled:opacity-50"
                        >
                          {deletingId === proj.id ? (
                            <Loader2 size={14} className="animate-spin text-red-600 shrink-0" />
                          ) : (
                            <Trash2 size={14} className="shrink-0" />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Individual Delete Confirmation Modal */}
      {confirmDeleteProject && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-slate-200/80 space-y-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-red-50 text-red-600 flex items-center justify-center shrink-0">
                  <Trash2 size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Delete Requisition</h3>
                  <p className="text-xs text-slate-500">This action cannot be undone</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConfirmDeleteProject(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to delete <strong className="text-slate-900">{confirmDeleteProject.title}</strong>? All associated screening scores, candidate rankings, and job description files will be removed from the database.
            </p>

            {deleteError && (
              <div className="p-3 bg-red-50 text-red-700 text-xs rounded-xl font-medium border border-red-200/80 flex items-center gap-2">
                <AlertCircle size={14} className="shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteProject(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deletingId === confirmDeleteProject.id}
                className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {deletingId === confirmDeleteProject.id ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <span>Confirm Delete</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete All Confirmation Modal */}
      {confirmDeleteAll && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-slate-200/80 space-y-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-red-50 text-red-600 flex items-center justify-center shrink-0">
                  <Trash2 size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Delete All Requisitions</h3>
                  <p className="text-xs text-slate-500">This action cannot be undone</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConfirmDeleteAll(false)}
                disabled={isDeletingAll}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to delete <strong className="text-slate-900">all {projects.length} {projects.length === 1 ? 'requisition' : 'requisitions'}</strong>? All associated screening scores, candidate rankings, and job description files will be permanently removed from the database.
            </p>

            {deleteError && (
              <div className="p-3 bg-red-50 text-red-700 text-xs rounded-xl font-medium border border-red-200/80 flex items-center gap-2">
                <AlertCircle size={14} className="shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteAll(false)}
                disabled={isDeletingAll}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDeleteAll}
                disabled={isDeletingAll}
                className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {isDeletingAll ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>Deleting All...</span>
                  </>
                ) : (
                  <span>Confirm Delete All</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
