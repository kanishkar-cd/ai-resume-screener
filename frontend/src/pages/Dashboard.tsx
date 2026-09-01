import { useEffect, useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderKanban,
  Building2,
  AlertCircle,
  ChevronRight,
  Search,
  Trash2,
  Loader2,
  X,
  Layers,
  BarChart3,
  ListOrdered,
  Plus,
  TrendingUp,
  ChevronLeft,
  FileText,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, Project } from '@/api'

const PAGE_SIZE = 8

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

export default function Dashboard() {
  const navigate = useNavigate()
  const { dispatch } = usePipeline()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDeptFilter, setSelectedDeptFilter] = useState<string>('ALL')
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<'ALL' | 'ACTIVE' | 'COMPLETED'>('ALL')
  const [currentPage, setCurrentPage] = useState<number>(1)

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

  const handleDepartmentFilterToggle = (deptName: string) => {
    setCurrentPage(1)
    if (selectedDeptFilter.toLowerCase() === deptName.toLowerCase()) {
      setSelectedDeptFilter('ALL')
    } else {
      setSelectedDeptFilter(deptName)
    }
  }

  const handleRequisitionClick = (proj: Project) => {
    const isCompleted = getRequisitionStatus(proj) === 'Completed'
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
    if (isCompleted) {
      navigate(`/projects/${proj.id}/reports`)
    } else {
      navigate(`/projects/${proj.id}/rankings`)
    }
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

  // Analytics computation
  const analytics = useMemo(() => {
    const total = projects.length
    let activeCount = 0
    let completedCount = 0
    let fresherCount = 0
    let experiencedCount = 0

    const deptMap: Record<string, number> = {}
    for (const d of DEPARTMENTS) {
      deptMap[d.name] = 0
    }

    for (const p of projects) {
      const status = getRequisitionStatus(p)
      if (status === 'Completed') completedCount++
      else activeCount++

      const exp = getExperienceLevel(p)
      if (exp === 'Fresher') fresherCount++
      else experiencedCount++

      const dName = p.department || 'General'
      deptMap[dName] = (deptMap[dName] || 0) + 1
    }

    const activeDepts = Object.keys(deptMap).filter((k) => (deptMap[k] || 0) > 0).length
    const activeRate = total > 0 ? Math.round((activeCount / total) * 100) : 0

    // Ranked list of departments sorted by requisition count descending
    const sortedDepts = DEPARTMENTS.map((dept) => ({
      ...dept,
      count: deptMap[dept.name] || 0,
      percentage: total > 0 ? Math.round(((deptMap[dept.name] || 0) / total) * 100) : 0,
    })).sort((a, b) => b.count - a.count)

    const topDept = sortedDepts[0]

    return {
      total,
      activeCount,
      completedCount,
      fresherCount,
      experiencedCount,
      activeDepts,
      activeRate,
      deptMap,
      sortedDepts,
      topDeptName: topDept?.count > 0 ? topDept.name : 'Engineering',
      topDeptCount: topDept?.count || 0,
    }
  }, [projects])

  // Filtered requisitions list
  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const matchesSearch =
        p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (p.department && p.department.toLowerCase().includes(searchTerm.toLowerCase())) ||
        (p.target_role && p.target_role.toLowerCase().includes(searchTerm.toLowerCase()))

      const matchesDept =
        selectedDeptFilter === 'ALL' ||
        (p.department && p.department.toLowerCase() === selectedDeptFilter.toLowerCase())

      const status = getRequisitionStatus(p)
      const matchesStatus =
        selectedStatusFilter === 'ALL' ||
        (selectedStatusFilter === 'ACTIVE' && status === 'Active') ||
        (selectedStatusFilter === 'COMPLETED' && status === 'Completed')

      return matchesSearch && matchesDept && matchesStatus
    })
  }, [projects, searchTerm, selectedDeptFilter, selectedStatusFilter])

  // Pagination calculation
  const totalPages = Math.max(1, Math.ceil(filteredProjects.length / PAGE_SIZE))
  const paginatedProjects = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return filteredProjects.slice(start, start + PAGE_SIZE)
  }, [filteredProjects, currentPage])

  const maxDeptCount = Math.max(...analytics.sortedDepts.map((d) => d.count), 1)

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header with Concise Dynamic Insight */}
      <div className="pb-4 border-b border-slate-200/70 flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
            Talent Analytics
          </h1>
          <p className="text-xs text-slate-500 mt-1 font-medium flex items-center gap-1.5 flex-wrap">
            <span>{analytics.total} total requisitions across {analytics.activeDepts} hiring departments.</span>
            <span className="text-slate-300">•</span>
            <span className="inline-flex items-center gap-1 text-slate-700 font-semibold">
              <TrendingUp size={13} className="text-blue-600" />
              Highest demand in <strong className="text-slate-900 font-bold">{analytics.topDeptName}</strong> ({analytics.topDeptCount} requisitions).
            </span>
          </p>
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

      {/* 3 Prominent KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Total Requisitions */}
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total Requisitions</p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading ? '...' : analytics.total}
            </p>
            <div className="mt-2.5">
              <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[11px] font-semibold">
                {analytics.fresherCount} Fresher · {analytics.experiencedCount} Exp
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
            <FolderKanban size={20} />
          </div>
        </div>

        {/* Active Requisitions */}
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Active Requisitions</p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading ? '...' : `${analytics.activeCount} of ${analytics.total}`}
            </p>
            <div className="mt-2.5">
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 text-[11px] font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {analytics.activeRate}% Active
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
            <Layers size={20} />
          </div>
        </div>

        {/* Hiring Departments */}
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Hiring Departments</p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {analytics.activeDepts} of {DEPARTMENTS.length}
            </p>
            <div className="mt-2.5">
              <span className="px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[11px] font-semibold">
                {DEPARTMENTS.length - analytics.activeDepts === 0 ? 'All units active' : `${analytics.activeDepts} active units`}
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
            <Building2 size={20} />
          </div>
        </div>
      </div>

      {/* Ranked Horizontal-Bar Visualization: Hiring Demand by Department */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-xs space-y-3">
        <div className="flex items-center justify-between pb-2.5 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <BarChart3 size={16} className="text-blue-600" />
            <h2 className="text-sm font-bold text-slate-900 tracking-tight">
              Hiring Demand by Department
            </h2>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-slate-400 font-semibold">
            {selectedDeptFilter !== 'ALL' && (
              <button
                type="button"
                onClick={() => setSelectedDeptFilter('ALL')}
                className="text-blue-600 hover:underline font-bold cursor-pointer"
              >
                Clear Filter ({selectedDeptFilter})
              </button>
            )}
            <span className="hidden sm:inline">Click a department to filter table</span>
          </div>
        </div>

        {/* 2-Column Responsive Ranked List */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 pt-1">
          {analytics.sortedDepts.map((dept, index) => {
            const count = dept.count
            const percentage = dept.percentage
            const isSelected = selectedDeptFilter.toLowerCase() === dept.name.toLowerCase()
            const hasZero = count === 0
            const barWidth = Math.round((count / maxDeptCount) * 100)

            return (
              <div
                key={dept.id}
                onClick={() => handleDepartmentFilterToggle(dept.name)}
                className={`flex items-center gap-3 p-2 rounded-xl border transition-all cursor-pointer group ${
                  isSelected
                    ? 'border-blue-500 bg-blue-50/50 ring-2 ring-blue-500/10'
                    : hasZero
                    ? 'border-transparent opacity-40 hover:opacity-75 hover:bg-slate-50'
                    : 'border-transparent hover:border-slate-200 hover:bg-slate-50/90'
                }`}
                title={`Filter by ${dept.name}`}
              >
                <div className="w-5 text-center text-[10px] font-bold text-slate-400 shrink-0">
                  #{index + 1}
                </div>

                <div className="w-36 truncate shrink-0">
                  <p className={`text-xs font-bold truncate transition-colors ${
                    isSelected ? 'text-blue-700' : 'text-slate-800 group-hover:text-blue-600'
                  }`}>
                    {dept.name}
                  </p>
                </div>

                <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden relative">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      isSelected
                        ? 'bg-blue-600'
                        : count > 0
                        ? 'bg-slate-700 group-hover:bg-blue-600'
                        : 'bg-slate-200'
                    }`}
                    style={{ width: `${Math.max(barWidth, count > 0 ? 6 : 0)}%` }}
                  />
                </div>

                <div className="w-20 text-right shrink-0 flex items-center justify-end gap-1 text-[11px]">
                  <strong className="text-slate-900 font-bold">{count}</strong>
                  <span className="text-slate-400 font-medium">({percentage}%)</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Requisitions Workspace (Main Focus) */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-xs space-y-4">
        {/* Section Header & Aligned Toolbar */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold text-slate-900 tracking-tight">
              Requisitions Workspace
            </h2>
            {!loading && !error && (
              <span className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[11px] font-bold border border-blue-100/80">
                {filteredProjects.length} {filteredProjects.length === 1 ? 'requisition' : 'requisitions'}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Status Tabs: All, Active, Completed */}
            <div className="flex items-center bg-slate-100 p-0.5 rounded-xl text-xs font-semibold text-slate-600">
              <button
                type="button"
                onClick={() => {
                  setSelectedStatusFilter('ALL')
                  setCurrentPage(1)
                }}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  selectedStatusFilter === 'ALL'
                    ? 'bg-white text-slate-900 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                All ({analytics.total})
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedStatusFilter('ACTIVE')
                  setCurrentPage(1)
                }}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  selectedStatusFilter === 'ACTIVE'
                    ? 'bg-white text-emerald-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                Active ({analytics.activeCount})
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedStatusFilter('COMPLETED')
                  setCurrentPage(1)
                }}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  selectedStatusFilter === 'COMPLETED'
                    ? 'bg-white text-blue-700 shadow-2xs font-bold'
                    : 'hover:text-slate-900'
                }`}
              >
                Completed ({analytics.completedCount})
              </button>
            </div>

            {/* Department Filter Dropdown */}
            <div className="relative">
              <select
                value={selectedDeptFilter}
                onChange={(e) => {
                  setSelectedDeptFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="pl-3 pr-8 py-1.5 bg-slate-50 border border-slate-200/80 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 cursor-pointer"
              >
                <option value="ALL">All Departments</option>
                {DEPARTMENTS.map((d) => (
                  <option key={d.id} value={d.name}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Search Input */}
            <div className="relative min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value)
                  setCurrentPage(1)
                }}
                placeholder="Search requisitions..."
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
            <span>Loading requisitions...</span>
          </div>
        ) : filteredProjects.length === 0 ? (
          <div className="py-16 text-center space-y-3.5 max-w-md mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
              <FolderKanban size={24} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {searchTerm || selectedDeptFilter !== 'ALL' || selectedStatusFilter !== 'ALL'
                  ? 'No matching requisitions'
                  : 'No requisitions yet'}
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                {searchTerm || selectedDeptFilter !== 'ALL' || selectedStatusFilter !== 'ALL'
                  ? 'Try adjusting your search query or department filter.'
                  : 'Get started by creating your first candidate screening campaign.'}
              </p>
            </div>
            {searchTerm || selectedDeptFilter !== 'ALL' || selectedStatusFilter !== 'ALL' ? (
              <button
                type="button"
                onClick={() => {
                  setSearchTerm('')
                  setSelectedDeptFilter('ALL')
                  setSelectedStatusFilter('ALL')
                  setCurrentPage(1)
                }}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors cursor-pointer"
              >
                <span>Reset Filters</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => navigate('/departments')}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors cursor-pointer"
              >
                <Plus size={14} />
                <span>Create Requisition</span>
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto border border-slate-100/90 rounded-xl">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50/80 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                    <th className="py-3 px-4.5">Requisition</th>
                    <th className="py-3 px-4">Department</th>
                    <th className="py-3 px-4">Target Role</th>
                    <th className="py-3 px-4 text-center">Experience</th>
                    <th className="py-3 px-4 text-center">Status</th>
                    <th className="py-3 px-4.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
                  {paginatedProjects.map((proj) => {
                    const status = getRequisitionStatus(proj)
                    const isCompleted = status === 'Completed'

                    return (
                      <tr
                        key={proj.id}
                        onClick={() => handleRequisitionClick(proj)}
                        className="hover:bg-blue-50/30 cursor-pointer transition-colors group"
                      >
                        <td className="py-3.5 px-4.5 font-bold text-slate-900">
                          <p className="group-hover:text-blue-600 transition-colors line-clamp-1">{proj.title}</p>
                        </td>
                        <td className="py-3.5 px-4">
                          <span className="inline-block px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[10px] font-bold font-mono tracking-tight">
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
                        <td className="py-3.5 px-4.5 text-right shrink-0">
                          <div className="inline-flex items-center justify-end gap-2 shrink-0 min-w-[160px]" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => handleRequisitionClick(proj)}
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

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-3 border-t border-slate-100 text-xs">
                <p className="text-slate-500 font-medium">
                  Showing <strong className="text-slate-900 font-bold">{(currentPage - 1) * PAGE_SIZE + 1}</strong> to{' '}
                  <strong className="text-slate-900 font-bold">
                    {Math.min(currentPage * PAGE_SIZE, filteredProjects.length)}
                  </strong>{' '}
                  of <strong className="text-slate-900 font-bold">{filteredProjects.length}</strong> requisitions
                </p>

                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                  >
                    <ChevronLeft size={14} />
                  </button>

                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((pg) => (
                    <button
                      key={pg}
                      type="button"
                      onClick={() => setCurrentPage(pg)}
                      className={`w-7 h-7 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                        currentPage === pg
                          ? 'bg-blue-600 text-white shadow-2xs'
                          : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      {pg}
                    </button>
                  ))}

                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </>
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
