import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Plus,
  Building2,
  Search,
  AlertCircle,
  Briefcase,
  Trash2,
  Loader2,
  X,
  ListOrdered,
  Cpu,
  LayoutGrid,
  Sparkles,
  TrendingUp,
  Shield,
  Users,
  FolderKanban,
  ChevronRight,
  FileText,
} from 'lucide-react'
import { DEPARTMENTS, Department } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, Project } from '@/api'

const ICON_MAP: Record<string, any> = {
  Cpu,
  LayoutGrid,
  Sparkles,
  TrendingUp,
  Shield,
  Users,
  Briefcase,
}

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

function getRequisitionStatus(proj: Project): 'Active' | 'Completed' {
  const statusUpper = (proj.status || '').toUpperCase()
  if (statusUpper === 'COMPLETED') return 'Completed'
  if (
    proj.metadata_json &&
    typeof proj.metadata_json === 'object' &&
    (proj.metadata_json as any).is_completed === true
  ) {
    return 'Completed'
  }
  return 'Active'
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

export default function DepartmentDashboard() {
  const { deptId } = useParams<{ deptId: string }>()
  const navigate = useNavigate()
  const { dispatch } = usePipeline()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'ACTIVE' | 'COMPLETED'>('ALL')

  // Delete state
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteProject, setConfirmDeleteProject] = useState<Project | null>(null)
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const department: Department =
    DEPARTMENTS.find((d) => d.id === deptId) || DEPARTMENTS[0]

  const fetchDeptProjects = useCallback(async () => {
    try {
      setLoading(true)
      const res = await api.listProjects()
      const deptItems = (res.items || []).filter(
        (p) =>
          (p.department && p.department.toLowerCase() === department.name.toLowerCase()) ||
          (p.department && p.department.toLowerCase() === department.code.toLowerCase())
      )
      setProjects(deptItems)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load department requisitions')
    } finally {
      setLoading(false)
    }
  }, [department.name, department.code])

  useEffect(() => {
    dispatch({ type: 'SET_DEPARTMENT_ID', payload: department.id })
    fetchDeptProjects()
  }, [department.id, fetchDeptProjects, dispatch])

  const handleSelectRequisition = (proj: Project) => {
    const isCompleted = getRequisitionStatus(proj) === 'Completed'
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
    if (isCompleted) {
      navigate(`/projects/${proj.id}/reports`)
    } else {
      navigate(`/projects/${proj.id}/rankings`)
    }
  }

  const handleNavigateCandidates = (e: React.MouseEvent, proj: Project) => {
    e.stopPropagation()
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
    navigate(`/projects/${proj.id}/candidates`)
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

  // Department metrics calculation
  const deptStats = useMemo(() => {
    let activeCount = 0
    let completedCount = 0
    let fresher = 0
    let experienced = 0
    const roles = new Set<string>()

    for (const p of projects) {
      if (p.target_role) roles.add(p.target_role)
      const status = getRequisitionStatus(p)
      if (status === 'Completed') completedCount++
      else activeCount++

      const exp = getExperienceLevel(p)
      if (exp === 'Fresher') fresher++
      else experienced++
    }

    return {
      total: projects.length,
      activeCount,
      completedCount,
      fresher,
      experienced,
      uniqueRolesCount: roles.size,
    }
  }, [projects])

  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const matchesSearch =
        p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (p.target_role && p.target_role.toLowerCase().includes(searchTerm.toLowerCase()))

      const status = getRequisitionStatus(p)
      const matchesStatus =
        statusFilter === 'ALL' ||
        (statusFilter === 'ACTIVE' && status === 'Active') ||
        (statusFilter === 'COMPLETED' && status === 'Completed')

      return matchesSearch && matchesStatus
    })
  }, [projects, searchTerm, statusFilter])

  const Icon = ICON_MAP[department.iconName] || Building2

  return (
    <div className="p-8 max-w-[1440px] mx-auto space-y-6">
      {/* Breadcrumb Hierarchy */}
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-400">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="hover:text-blue-600 transition-colors cursor-pointer"
        >
          Overview
        </button>
        <ChevronRight size={13} className="text-slate-300" />
        <button
          type="button"
          onClick={() => navigate('/departments')}
          className="hover:text-blue-600 transition-colors cursor-pointer"
        >
          Departments
        </button>
        <ChevronRight size={13} className="text-slate-300" />
        <span className="text-slate-700 font-bold">{department.name}</span>
      </div>

      {/* Prominent Department Hero Banner */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-start md:items-center gap-4">
          <div className={`w-14 h-14 rounded-2xl ${department.badgeBg} flex items-center justify-center shrink-0 shadow-xs`}>
            <Icon size={26} className={department.badgeText} />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
                {department.name}
              </h1>
              <span className="px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-700 text-xs font-bold font-mono tracking-tight">
                {department.code}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl font-medium leading-relaxed">
              {department.description}
            </p>
          </div>
        </div>

        <div className="shrink-0 self-start md:self-auto">
          <button
            type="button"
            onClick={() => navigate(`/departments/${department.id}/requisitions/new`)}
            className="inline-flex items-center gap-2 px-4.5 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-xl text-xs font-bold shadow-xs hover:shadow-md transition-all cursor-pointer shrink-0"
          >
            <Plus size={15} />
            <span>Create Requisition</span>
          </button>
        </div>
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

      {/* Recruiter Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Department Requisitions */}
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Department Requisitions</p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading ? '...' : deptStats.total}
            </p>
            <div className="mt-2.5">
              <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[11px] font-semibold">
                {deptStats.fresher} Fresher · {deptStats.experienced} Experienced
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
            <FolderKanban size={20} />
          </div>
        </div>

        {/* Target Role Profiles */}
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Target Role Profiles</p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading ? '...' : deptStats.uniqueRolesCount}
            </p>
            <div className="mt-2.5">
              <span className="px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[11px] font-semibold">
                Unique role specifications defined
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
            <Briefcase size={20} />
          </div>
        </div>
      </div>

      {/* Requisitions Workspace Table Section */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs space-y-4">
        {/* Workspace Toolbar: Status Tabs & Search */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold text-slate-900 tracking-tight">
              {department.name} Requisitions
            </h2>
            {!loading && !error && (
              <span className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[11px] font-bold border border-blue-100/80">
                {filteredProjects.length} {filteredProjects.length === 1 ? 'requisition' : 'requisitions'}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Status Filter Tabs: All, Active, Completed */}
            <div className="flex items-center bg-slate-100 p-0.5 rounded-xl text-xs font-semibold text-slate-600">
              <button
                type="button"
                onClick={() => setStatusFilter('ALL')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  statusFilter === 'ALL'
                    ? 'bg-white text-slate-900 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                All ({deptStats.total})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('ACTIVE')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  statusFilter === 'ACTIVE'
                    ? 'bg-white text-emerald-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                Active ({deptStats.activeCount})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('COMPLETED')}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  statusFilter === 'COMPLETED'
                    ? 'bg-white text-blue-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                Completed ({deptStats.completedCount})
              </button>
            </div>

            {/* Search Input */}
            <div className="relative min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search requisitions or roles..."
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

        {/* Table Content & Intentional Empty State */}
        {loading ? (
          <div className="py-16 text-center text-xs text-slate-400 font-medium flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin text-blue-600" />
            <span>Loading department requisitions...</span>
          </div>
        ) : filteredProjects.length === 0 ? (
          <div className="py-16 text-center space-y-3.5 max-w-md mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
              <FolderKanban size={24} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {searchTerm || statusFilter !== 'ALL'
                  ? 'No matching requisitions'
                  : `No requisitions in ${department.name}`}
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                {searchTerm || statusFilter !== 'ALL'
                  ? 'Try adjusting your search query or status filter.'
                  : `Create the first candidate screening campaign for ${department.name}.`}
              </p>
            </div>
            {searchTerm || statusFilter !== 'ALL' ? (
              <button
                type="button"
                onClick={() => {
                  setSearchTerm('')
                  setStatusFilter('ALL')
                }}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors cursor-pointer"
              >
                <span>Reset Filters</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => navigate(`/departments/${department.id}/requisitions/new`)}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors cursor-pointer"
              >
                <Plus size={14} />
                <span>Create Requisition</span>
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto border border-slate-100/90 rounded-xl">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <th className="py-3 px-4.5">Requisition</th>
                  <th className="py-3 px-4">Target Role</th>
                  <th className="py-3 px-4 text-center">Experience</th>
                  <th className="py-3 px-4 text-center">Candidates</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4 text-center">Created On</th>
                  <th className="py-3 px-4.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                {filteredProjects.map((proj) => {
                  const status = getRequisitionStatus(proj)
                  const isCompleted = status === 'Completed'

                  return (
                    <tr
                      key={proj.id}
                      onClick={() => handleSelectRequisition(proj)}
                      className="hover:bg-blue-50/30 cursor-pointer transition-colors group"
                    >
                      <td className="py-3.5 px-4.5 font-bold text-slate-900">
                        <p className="group-hover:text-blue-600 transition-colors line-clamp-1">{proj.title}</p>
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
                        <button
                          type="button"
                          onClick={(e) => handleNavigateCandidates(e, proj)}
                          className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md text-[11px] font-semibold transition-colors cursor-pointer"
                        >
                          <Users size={12} className="text-slate-500" />
                          <span>View Pipeline</span>
                        </button>
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                            isCompleted
                              ? 'bg-blue-50 text-blue-700 border-blue-200/60'
                              : 'bg-emerald-50 text-emerald-700 border-emerald-200/60'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              isCompleted ? 'bg-blue-500' : 'bg-emerald-500'
                            }`}
                          />
                          {status}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-center text-slate-500 text-[11px] font-medium">
                        {formatDate(proj.created_at)}
                      </td>
                      <td className="py-3.5 px-4.5 text-right shrink-0">
                        <div className="inline-flex items-center justify-end gap-2 shrink-0 min-w-[150px]" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => handleSelectRequisition(proj)}
                            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all shadow-2xs cursor-pointer ${
                              isCompleted
                                ? 'bg-blue-600 text-white hover:bg-blue-700'
                                : 'bg-blue-50 hover:bg-blue-600 text-blue-700 hover:text-white'
                            }`}
                          >
                            {isCompleted ? <FileText size={13} /> : <ListOrdered size={13} />}
                            <span>{isCompleted ? 'View Report' : 'View Rankings'}</span>
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
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Single Delete Confirmation Modal */}
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
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer"
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
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
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
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors disabled:opacity-50 cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to delete <strong className="text-slate-900">all {projects.length} {projects.length === 1 ? 'requisition' : 'requisitions'}</strong> for <strong className="text-slate-900">{department.name}</strong>? All associated screening scores, candidate rankings, and job description files will be permanently removed from the database.
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
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-50 cursor-pointer"
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
