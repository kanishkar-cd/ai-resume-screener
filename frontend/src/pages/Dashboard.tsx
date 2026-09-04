import { useEffect, useState, useMemo, useCallback } from 'react'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import {
  FolderKanban,
  Building2,
  AlertCircle,
  ChevronRight,
  Search,
  Briefcase,
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
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, Project } from '@/api'

const PAGE_SIZE = 8

type SortField = 'title' | 'department' | 'target_role' | 'experience' | 'status' | 'created_at'
const VALID_SORT_FIELDS: SortField[] = ['title', 'department', 'target_role', 'experience', 'status', 'created_at']

function getExperienceLevel(proj: Project): 'Fresher' | 'Experienced' {
  if (!proj) return 'Fresher'
  const meta = proj.metadata_json && typeof proj.metadata_json === 'object' ? proj.metadata_json : {}

  // 1. Structured metadata: explicit experience_level or level
  const explicitLevel = (meta as any).experience_level || (meta as any).level || (meta as any).seniority
  if (typeof explicitLevel === 'string' && explicitLevel.trim()) {
    const l = explicitLevel.toLowerCase().trim()
    if (
      l.includes('fresher') ||
      l.includes('entry') ||
      l.includes('intern') ||
      l.includes('graduate') ||
      l.includes('trainee') ||
      l === '0-1' ||
      l === '0-1 year' ||
      l === '0-1 yr' ||
      l === '0-1 yrs'
    ) {
      return 'Fresher'
    }
    if (
      l.includes('experienced') ||
      l.includes('senior') ||
      l.includes('lead') ||
      l.includes('mid') ||
      l.includes('principal') ||
      l.includes('expert') ||
      l.includes('yr') ||
      l.includes('year')
    ) {
      return 'Experienced'
    }
  }

  // 2. Structured metadata: numeric years or months
  const minYears = (meta as any).min_experience_years ?? (meta as any).min_years ?? (meta as any).years_experience
  if (typeof minYears === 'number') {
    return minYears >= 1 ? 'Experienced' : 'Fresher'
  }
  const minMonths = (meta as any).min_experience_months ?? (meta as any).min_months
  if (typeof minMonths === 'number') {
    return minMonths > 12 ? 'Experienced' : 'Fresher'
  }

  // 3. Inspect Target Role & Title for explicit seniority or entry signals
  const titleAndRole = `${proj.title || ''} ${proj.target_role || ''}`.toLowerCase()

  // High confidence Fresher/Intern indicators
  if (/\b(intern|internship|fresher|graduate trainee|entry level|entry-level|trainee|apprentice)\b/i.test(titleAndRole)) {
    return 'Fresher'
  }

  // High confidence Experienced indicators
  if (/\b(senior|sr\.?|lead|principal|staff|architect|manager|director|head|vp|mid-level|mid level|experienced|specialist|expert)\b/i.test(titleAndRole)) {
    return 'Experienced'
  }

  // 4. Inspect Description for experience range expressions
  const desc = (proj.description || '').toLowerCase()

  // Matches "0-1 year", "0 to 1 yr", "no experience required", "freshers can apply"
  if (/\b(0\s*[-–to]\s*1\s*(?:year|yr)|0\s*(?:year|yr)|no\s+experience|freshers?\s+(?:can|welcome|only)|recent\s+graduates?)\b/i.test(desc)) {
    return 'Fresher'
  }

  // Matches "1+ year", "2-5 years", "3 to 5 yrs", "minimum 2 years", "at least 1 year"
  if (
    /\b([1-9]\d*|\d+\.\d+)\+?\s*(?:to|-|–)?\s*\d*\s*(?:years?|yrs?|yr)\b/i.test(desc) ||
    /\b(at\s+least|minimum|min\.?)\s+([1-9]\d*)\s*(?:years?|yrs?|yr)\b/i.test(desc)
  ) {
    return 'Experienced'
  }

  // 5. General keyword indicators in description
  if (desc.includes('experienced') || desc.includes('senior') || desc.includes('proven track record') || desc.includes('prior experience')) {
    return 'Experienced'
  }
  if (desc.includes('fresher') || desc.includes('entry-level') || desc.includes('entry level')) {
    return 'Fresher'
  }

  // 6. Title junior indicators
  if (/\b(junior|jr\.?|associate)\b/i.test(titleAndRole)) {
    return 'Fresher'
  }

  // 7. Safe fallback based on project status and standard professional role default
  return 'Experienced'
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
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const { dispatch } = usePipeline()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Derive filter and sort state directly from URL searchParams
  const searchTerm = searchParams.get('q') || ''
  const selectedDeptFilter = searchParams.get('dept') || 'ALL'
  const rawStatus = (searchParams.get('status') || 'ALL').toUpperCase()
  const selectedStatusFilter: 'ALL' | 'ACTIVE' | 'COMPLETED' =
    rawStatus === 'ACTIVE' || rawStatus === 'COMPLETED' ? rawStatus : 'ALL'
  const rawPage = parseInt(searchParams.get('page') || '1', 10)
  const currentPage = !isNaN(rawPage) && rawPage > 0 ? rawPage : 1

  const rawSortBy = (searchParams.get('sort_by') || 'created_at') as SortField
  const sortBy: SortField = VALID_SORT_FIELDS.includes(rawSortBy) ? rawSortBy : 'created_at'
  const rawSortDir = (searchParams.get('sort_dir') || 'desc').toLowerCase()
  const sortDir: 'asc' | 'desc' = rawSortDir === 'asc' ? 'asc' : 'desc'

  const updateUrlParams = useCallback(
    (updates: {
      q?: string
      dept?: string
      status?: string
      page?: number
      sortBy?: SortField
      sortDir?: 'asc' | 'desc'
    }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (updates.q !== undefined) {
            const trimmed = updates.q.trim()
            if (trimmed) next.set('q', updates.q)
            else next.delete('q')
          }
          if (updates.dept !== undefined) {
            if (updates.dept && updates.dept !== 'ALL') next.set('dept', updates.dept)
            else next.delete('dept')
          }
          if (updates.status !== undefined) {
            if (updates.status && updates.status !== 'ALL') next.set('status', updates.status.toLowerCase())
            else next.delete('status')
          }
          if (updates.sortBy !== undefined) {
            if (updates.sortBy && updates.sortBy !== 'created_at') next.set('sort_by', updates.sortBy)
            else next.delete('sort_by')
          }
          if (updates.sortDir !== undefined) {
            if (updates.sortDir && updates.sortDir !== 'desc') next.set('sort_dir', updates.sortDir)
            else next.delete('sort_dir')
          }
          if (updates.page !== undefined) {
            if (updates.page > 1) next.set('page', String(updates.page))
            else next.delete('page')
          }
          return next
        },
        { replace: true }
      )
    },
    [setSearchParams]
  )

  const handleSortToggle = (field: SortField) => {
    if (sortBy === field) {
      updateUrlParams({ sortDir: sortDir === 'asc' ? 'desc' : 'asc', page: 1 })
    } else {
      updateUrlParams({
        sortBy: field,
        sortDir: field === 'created_at' ? 'desc' : 'asc',
        page: 1,
      })
    }
  }

  const renderSortIndicator = (field: SortField) => {
    if (sortBy !== field) {
      return <ArrowUpDown size={12} className="text-slate-300 group-hover/col:text-slate-500 shrink-0 transition-colors" />
    }
    if (sortDir === 'asc') {
      return <ArrowUp size={12} className="text-blue-600 shrink-0" />
    }
    return <ArrowDown size={12} className="text-blue-600 shrink-0" />
  }

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

  // Dynamic list of unique department names derived from projects, merged with standard DEPARTMENTS
  const availableDepartments = useMemo(() => {
    const deptSet = new Map<string, string>()

    // 1. Gather all departments actually used across active projects
    for (const p of projects) {
      const name = (p.department || 'General').trim()
      if (name && !deptSet.has(name.toLowerCase())) {
        deptSet.set(name.toLowerCase(), name)
      }
    }

    // 2. Also register standard departments from constants if not present
    for (const d of DEPARTMENTS) {
      if (!deptSet.has(d.name.toLowerCase())) {
        deptSet.set(d.name.toLowerCase(), d.name)
      }
    }

    return Array.from(deptSet.values()).sort((a, b) => a.localeCompare(b))
  }, [projects])

  const handleDepartmentFilterToggle = (deptName: string) => {
    if (selectedDeptFilter.toLowerCase() === deptName.toLowerCase()) {
      updateUrlParams({ dept: 'ALL', page: 1 })
    } else {
      updateUrlParams({ dept: deptName, page: 1 })
    }
  }

  const handleRequisitionClick = (proj: Project) => {
    const isCompleted = getRequisitionStatus(proj) === 'Completed'
    const rawDept = (proj.department || 'General').trim()
    const dept = DEPARTMENTS.find((d) => d.name.toLowerCase() === rawDept.toLowerCase())
    if (dept) {
      dispatch({ type: 'SET_DEPARTMENT_ID', payload: dept.id })
    } else {
      dispatch({ type: 'SET_DEPARTMENT_ID', payload: rawDept.toLowerCase().replace(/\s+/g, '-') })
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
      navigate(`/projects/${proj.id}/assessment`)
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
    for (const d of availableDepartments) {
      deptMap[d] = 0
    }

    for (const p of projects) {
      const status = getRequisitionStatus(p)
      if (status === 'Completed') completedCount++
      else activeCount++

      const exp = getExperienceLevel(p)
      if (exp === 'Fresher') fresherCount++
      else experiencedCount++

      const rawDept = (p.department || 'General').trim()
      const matchedDept = availableDepartments.find((d) => d.toLowerCase() === rawDept.toLowerCase()) || rawDept
      deptMap[matchedDept] = (deptMap[matchedDept] || 0) + 1
    }

    const activeDepts = Object.keys(deptMap).filter((k) => (deptMap[k] || 0) > 0).length
    const activeRate = total > 0 ? Math.round((activeCount / total) * 100) : 0

    // Ranked list of departments sorted by requisition count descending
    const sortedDepts = availableDepartments.map((deptName) => {
      const standard = DEPARTMENTS.find((d) => d.name.toLowerCase() === deptName.toLowerCase())
      return {
        id: standard?.id || deptName.toLowerCase().replace(/\s+/g, '-'),
        name: deptName,
        code: standard?.code || deptName.substring(0, 3).toUpperCase(),
        count: deptMap[deptName] || 0,
        percentage: total > 0 ? Math.round(((deptMap[deptName] || 0) / total) * 100) : 0,
      }
    })
    .filter((d) => d.count > 0 || DEPARTMENTS.some((std) => std.name.toLowerCase() === d.name.toLowerCase()))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))

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
  }, [projects, availableDepartments])

  // Department-specific analytics computation when scoped to a department
  const isDeptScoped = selectedDeptFilter !== 'ALL'

  const activeDepartmentObj = useMemo(() => {
    if (!isDeptScoped) return null
    return (
      DEPARTMENTS.find(
        (d) =>
          d.name.toLowerCase() === selectedDeptFilter.toLowerCase() ||
          d.id.toLowerCase() === selectedDeptFilter.toLowerCase() ||
          d.code.toLowerCase() === selectedDeptFilter.toLowerCase()
      ) || null
    )
  }, [isDeptScoped, selectedDeptFilter])

  const deptProjects = useMemo(() => {
    if (!isDeptScoped) return projects
    return projects.filter(
      (p) => (p.department || 'General').trim().toLowerCase() === selectedDeptFilter.trim().toLowerCase()
    )
  }, [projects, isDeptScoped, selectedDeptFilter])

  const deptAnalytics = useMemo(() => {
    const total = deptProjects.length
    let activeCount = 0
    let completedCount = 0
    let fresherCount = 0
    let experiencedCount = 0

    for (const p of deptProjects) {
      const status = getRequisitionStatus(p)
      if (status === 'Completed') completedCount++
      else activeCount++

      const exp = getExperienceLevel(p)
      if (exp === 'Fresher') fresherCount++
      else experiencedCount++
    }

    const activeRate = total > 0 ? Math.round((activeCount / total) * 100) : 0

    return {
      total,
      activeCount,
      completedCount,
      fresherCount,
      experiencedCount,
      activeRate,
    }
  }, [deptProjects])

  // Filtered requisitions list
  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const projDept = (p.department || 'General').trim()
      const matchesSearch =
        p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        projDept.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (p.target_role && p.target_role.toLowerCase().includes(searchTerm.toLowerCase()))

      const matchesDept =
        selectedDeptFilter === 'ALL' ||
        projDept.toLowerCase() === selectedDeptFilter.trim().toLowerCase()

      const status = getRequisitionStatus(p)
      const matchesStatus =
        selectedStatusFilter === 'ALL' ||
        (selectedStatusFilter === 'ACTIVE' && status === 'Active') ||
        (selectedStatusFilter === 'COMPLETED' && status === 'Completed')

      return matchesSearch && matchesDept && matchesStatus
    })
  }, [projects, searchTerm, selectedDeptFilter, selectedStatusFilter])

  // Sort filtered requisitions
  const sortedProjects = useMemo(() => {
    return [...filteredProjects].sort((a, b) => {
      let cmp = 0
      switch (sortBy) {
        case 'title':
          cmp = (a.title || '').localeCompare(b.title || '', undefined, { sensitivity: 'base' })
          break
        case 'department': {
          const deptA = (a.department || 'General').trim()
          const deptB = (b.department || 'General').trim()
          cmp = deptA.localeCompare(deptB, undefined, { sensitivity: 'base' })
          break
        }
        case 'target_role': {
          const roleA = (a.target_role || '').trim()
          const roleB = (b.target_role || '').trim()
          cmp = roleA.localeCompare(roleB, undefined, { sensitivity: 'base' })
          break
        }
        case 'experience': {
          const expA = getExperienceLevel(a)
          const expB = getExperienceLevel(b)
          cmp = expA.localeCompare(expB)
          break
        }
        case 'status': {
          const statA = getRequisitionStatus(a)
          const statB = getRequisitionStatus(b)
          cmp = statA.localeCompare(statB)
          break
        }
        case 'created_at':
        default: {
          const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
          const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
          cmp = timeA - timeB
          break
        }
      }
      if (cmp !== 0) {
        return sortDir === 'asc' ? cmp : -cmp
      }
      // Stable secondary tie-breaker
      return a.id.localeCompare(b.id)
    })
  }, [filteredProjects, sortBy, sortDir])

  // Pagination calculation
  const totalPages = Math.max(1, Math.ceil(sortedProjects.length / PAGE_SIZE))
  const effectivePage = Math.min(currentPage, totalPages)
  const paginatedProjects = useMemo(() => {
    const start = (effectivePage - 1) * PAGE_SIZE
    return sortedProjects.slice(start, start + PAGE_SIZE)
  }, [sortedProjects, effectivePage])

  // If items are deleted and current page exceeds new totalPages, clamp URL page safely
  useEffect(() => {
    if (currentPage > totalPages && totalPages >= 1 && !loading) {
      updateUrlParams({ page: totalPages })
    }
  }, [currentPage, totalPages, loading, updateUrlParams])

  const maxDeptCount = Math.max(...analytics.sortedDepts.map((d) => d.count), 1)

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header with Concise Dynamic Insight */}
      <div className="pb-4 border-b border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {isDeptScoped ? (
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 mb-1">
              <button
                type="button"
                onClick={() => updateUrlParams({ dept: 'ALL', page: 1 })}
                className="hover:text-slate-900 transition-colors cursor-pointer"
              >
                Overview
              </button>
              <ChevronRight size={12} className="text-slate-300" />
              <span className="text-slate-800 font-semibold">{selectedDeptFilter}</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2.5">
              <Building2 size={22} className="text-slate-700" />
              {selectedDeptFilter} Dashboard
            </h1>
            <p className="text-xs text-slate-500 mt-1 font-medium flex items-center gap-1.5 flex-wrap">
              <span>{deptAnalytics.total} total requisitions in {selectedDeptFilter}.</span>
              <span className="text-slate-300">•</span>
              <span>
                {deptAnalytics.activeCount} active ({deptAnalytics.activeRate}%) · {deptAnalytics.completedCount} completed
              </span>
            </p>
          </div>
        ) : (
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
              Talent Analytics
            </h1>
            <p className="text-xs text-slate-500 mt-1 font-medium flex items-center gap-1.5 flex-wrap">
              <span>{analytics.total} total requisitions across {analytics.activeDepts} hiring departments.</span>
              <span className="text-slate-300">•</span>
              <span>
                Top hiring demand in <strong className="text-slate-800 font-semibold">{analytics.topDeptName}</strong> ({analytics.topDeptCount} requisitions).
              </span>
            </p>
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (isDeptScoped && activeDepartmentObj) {
                navigate(`/departments/${activeDepartmentObj.id}/requisitions/new`)
              } else {
                navigate('/departments')
              }
            }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer"
          >
            <Plus size={14} />
            <span>New Requisition</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 text-xs font-medium shadow-xs">
          <AlertCircle size={16} className="shrink-0 text-red-600" />
          <div>
            <p className="font-bold">Backend Service Error</p>
            <p className="text-[11px] text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Modern KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Total Requisitions */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs hover:border-slate-300 transition-colors flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              {isDeptScoped ? `${selectedDeptFilter} Requisitions` : 'Total Requisitions'}
            </p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading ? '...' : isDeptScoped ? deptAnalytics.total : analytics.total}
            </p>
            <div className="mt-2.5">
              <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[11px] font-medium border border-slate-200/60">
                {isDeptScoped ? deptAnalytics.fresherCount : analytics.fresherCount} Fresher ·{' '}
                {isDeptScoped ? deptAnalytics.experiencedCount : analytics.experiencedCount} Exp
              </span>
            </div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-600 flex items-center justify-center shrink-0 border border-slate-200/60">
            <FolderKanban size={18} />
          </div>
        </div>

        {/* Active Requisitions */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs hover:border-slate-300 transition-colors flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              {isDeptScoped ? `${selectedDeptFilter} Active Requisitions` : 'Active Requisitions'}
            </p>
            <p className="text-3xl font-extrabold text-slate-900 mt-1 tracking-tight">
              {loading
                ? '...'
                : isDeptScoped
                ? `${deptAnalytics.activeCount} of ${deptAnalytics.total}`
                : `${analytics.activeCount} of ${analytics.total}`}
            </p>
            <div className="mt-2.5">
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 text-[11px] font-medium border border-emerald-200/60">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {isDeptScoped ? deptAnalytics.activeRate : analytics.activeRate}% Active
              </span>
            </div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-600 flex items-center justify-center shrink-0 border border-slate-200/60">
            <Layers size={18} />
          </div>
        </div>
      </div>

      {/* Ranked Horizontal-Bar Visualization: Hiring Demand by Department (Overview Only) */}
      {!isDeptScoped && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3.5">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <BarChart3 size={16} className="text-slate-700" />
              <h2 className="text-sm font-bold text-slate-900 tracking-tight">
                Hiring Demand by Department
              </h2>
            </div>
            <div className="text-[11px] text-slate-400 font-medium">
              Click a department to open its dashboard
            </div>
          </div>

          {/* 2-Column Responsive Ranked List */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5 pt-0.5">
            {analytics.sortedDepts.map((dept, index) => {
              const count = dept.count
              const percentage = dept.percentage
              const hasZero = count === 0
              const barWidth = Math.round((count / maxDeptCount) * 100)

              return (
                <div
                  key={dept.id}
                  onClick={() => handleDepartmentFilterToggle(dept.name)}
                  className={`flex items-center gap-3 p-2 rounded-lg border transition-colors cursor-pointer group ${
                    hasZero
                      ? 'border-transparent opacity-40 hover:opacity-75 hover:bg-slate-50'
                      : 'border-transparent hover:border-slate-200 hover:bg-slate-50'
                  }`}
                  title={`Open ${dept.name} Dashboard`}
                >
                  <div className="w-5 text-center text-[11px] font-semibold text-slate-400 shrink-0">
                    #{index + 1}
                  </div>

                  <div className="w-36 truncate shrink-0">
                    <p className="text-xs font-semibold truncate transition-colors text-slate-800 group-hover:text-blue-600">
                      {dept.name}
                    </p>
                  </div>

                  <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden relative">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        count > 0 ? 'bg-slate-700 group-hover:bg-blue-600' : 'bg-slate-200'
                      }`}
                      style={{ width: `${Math.max(barWidth, count > 0 ? 6 : 0)}%` }}
                    />
                  </div>

                  <div className="w-20 text-right shrink-0 flex items-center justify-end gap-1 text-[11px]">
                    <strong className="text-slate-900 font-bold">{count}</strong>
                    <span className="text-slate-400 font-normal">({percentage}%)</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Requisitions Workspace (Main Focus) */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
        {/* Section Header & Aligned Toolbar */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 pb-3 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <h2 className="text-sm font-bold text-slate-900 tracking-tight">
              {isDeptScoped ? `${selectedDeptFilter} Requisitions` : 'Requisitions Workspace'}
            </h2>
            {!loading && !error && (
              <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[11px] font-semibold border border-slate-200/60">
                {filteredProjects.length} {filteredProjects.length === 1 ? 'requisition' : 'requisitions'}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Status Tabs: All, Active, Completed */}
            <div className="flex items-center bg-slate-100 p-0.5 rounded-lg text-xs font-medium text-slate-600">
              <button
                type="button"
                onClick={() => updateUrlParams({ status: 'ALL', page: 1 })}
                className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                  selectedStatusFilter === 'ALL'
                    ? 'bg-white text-slate-900 shadow-xs font-semibold'
                    : 'hover:text-slate-900'
                }`}
              >
                All ({isDeptScoped ? deptAnalytics.total : analytics.total})
              </button>
              <button
                type="button"
                onClick={() => updateUrlParams({ status: 'ACTIVE', page: 1 })}
                className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                  selectedStatusFilter === 'ACTIVE'
                    ? 'bg-white text-emerald-700 shadow-xs font-semibold'
                    : 'hover:text-slate-900'
                }`}
              >
                Active ({isDeptScoped ? deptAnalytics.activeCount : analytics.activeCount})
              </button>
              <button
                type="button"
                onClick={() => updateUrlParams({ status: 'COMPLETED', page: 1 })}
                className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                  selectedStatusFilter === 'COMPLETED'
                    ? 'bg-white text-slate-900 shadow-xs font-semibold'
                    : 'hover:text-slate-900'
                }`}
              >
                Completed ({isDeptScoped ? deptAnalytics.completedCount : analytics.completedCount})
              </button>
            </div>

            {/* Department Filter Dropdown (Overview Dashboard Only) */}
            {!isDeptScoped && (
              <div className="relative">
                <select
                  value={selectedDeptFilter}
                  onChange={(e) => updateUrlParams({ dept: e.target.value, page: 1 })}
                  className="pl-3 pr-8 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 cursor-pointer shadow-2xs"
                >
                  <option value="ALL">All Departments</option>
                  {availableDepartments.map((deptName) => (
                    <option key={deptName} value={deptName}>
                      {deptName}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Search Input */}
            <div className="relative min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => updateUrlParams({ q: e.target.value, page: 1 })}
                placeholder={isDeptScoped ? `Search ${selectedDeptFilter} requisitions...` : 'Search requisitions...'}
                className="w-full pl-8 pr-3.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-medium text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 placeholder:text-slate-400 transition-colors shadow-2xs"
              />
            </div>

            {projects.length > 0 && (
              <div className="flex items-center pl-1 border-l border-slate-200">
                <button
                  type="button"
                  onClick={handleDeleteAllClick}
                  disabled={isDeletingAll}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-600 hover:text-red-700 bg-white hover:bg-red-50 border border-slate-200 hover:border-red-200 rounded-lg transition-colors cursor-pointer shrink-0 disabled:opacity-50"
                  title="Delete all requisitions"
                >
                  <Trash2 size={13} className="shrink-0" />
                  <span>Delete All</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Table Content & Intentional Empty State */}
        {loading ? (
          <div className="py-16 text-center text-xs text-slate-400 font-medium flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin text-slate-600" />
            <span>Loading requisitions...</span>
          </div>
        ) : filteredProjects.length === 0 ? (
          <div className="py-16 text-center space-y-3.5 max-w-md mx-auto">
            <div className="w-12 h-12 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto border border-slate-200/60">
              <FolderKanban size={22} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {isDeptScoped && deptProjects.length === 0
                  ? `No requisitions in ${selectedDeptFilter} yet`
                  : searchTerm || selectedStatusFilter !== 'ALL'
                  ? 'No matching requisitions'
                  : 'No requisitions yet'}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {isDeptScoped && deptProjects.length === 0
                  ? `Get started by creating the first candidate screening campaign for ${selectedDeptFilter}.`
                  : searchTerm || selectedStatusFilter !== 'ALL'
                  ? 'Try adjusting your search query or status filter.'
                  : 'Get started by creating your first candidate screening campaign.'}
              </p>
            </div>
            {searchTerm || selectedStatusFilter !== 'ALL' ? (
              <button
                type="button"
                onClick={() => updateUrlParams({ q: '', status: 'ALL', page: 1 })}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition-colors cursor-pointer"
              >
                <span>Reset Search & Filter</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  if (isDeptScoped && activeDepartmentObj) {
                    navigate(`/departments/${activeDepartmentObj.id}/requisitions/new`)
                  } else {
                    navigate('/departments')
                  }
                }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer"
              >
                <Plus size={14} />
                <span>Create Requisition</span>
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto border border-slate-200 rounded-lg">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-200 select-none">
                    <th
                      className="py-2.5 px-4 min-w-[240px] max-w-[380px] cursor-pointer hover:text-slate-800 transition-colors group/col"
                      onClick={() => handleSortToggle('title')}
                      title="Sort by Requisition Title"
                    >
                      <div className="flex items-center gap-1.5">
                        <span>Requisition</span>
                        {renderSortIndicator('title')}
                      </div>
                    </th>
                    <th
                      className="py-2.5 px-4 w-36 cursor-pointer hover:text-slate-800 transition-colors group/col"
                      onClick={() => handleSortToggle('department')}
                      title="Sort by Department"
                    >
                      <div className="flex items-center gap-1.5">
                        <span>Department</span>
                        {renderSortIndicator('department')}
                      </div>
                    </th>
                    <th
                      className="py-2.5 px-4 min-w-[140px] cursor-pointer hover:text-slate-800 transition-colors group/col"
                      onClick={() => handleSortToggle('target_role')}
                      title="Sort by Target Role"
                    >
                      <div className="flex items-center gap-1.5">
                        <span>Target Role</span>
                        {renderSortIndicator('target_role')}
                      </div>
                    </th>
                    <th
                      className="py-2.5 px-4 w-28 text-center cursor-pointer hover:text-slate-800 transition-colors group/col"
                      onClick={() => handleSortToggle('experience')}
                      title="Sort by Experience Level"
                    >
                      <div className="inline-flex items-center justify-center gap-1.5">
                        <span>Experience</span>
                        {renderSortIndicator('experience')}
                      </div>
                    </th>
                    <th
                      className="py-2.5 px-4 w-28 text-center cursor-pointer hover:text-slate-800 transition-colors group/col"
                      onClick={() => handleSortToggle('status')}
                      title="Sort by Status"
                    >
                      <div className="inline-flex items-center justify-center gap-1.5">
                        <span>Status</span>
                        {renderSortIndicator('status')}
                      </div>
                    </th>
                    <th className="py-2.5 px-4 w-44 text-right">Actions</th>
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
                        className="hover:bg-slate-50/75 cursor-pointer transition-colors group"
                      >
                        <td className="py-3 px-4 font-bold text-slate-900 min-w-[240px] max-w-[380px]" title={proj.title}>
                          <p className="group-hover:text-blue-600 transition-colors line-clamp-2 break-words leading-snug">
                            {proj.title}
                          </p>
                        </td>
                        <td className="py-3 px-4 w-36">
                          <span className="inline-block px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[10px] font-semibold font-mono tracking-tight border border-slate-200/60">
                            {proj.department || 'General'}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-slate-600 font-medium min-w-[140px]" title={proj.target_role || undefined}>
                          <p className="line-clamp-1 truncate">{proj.target_role || '—'}</p>
                        </td>
                        <td className="py-3 px-4 w-28 text-center">
                          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200/60">
                            {getExperienceLevel(proj)}
                          </span>
                        </td>
                        <td className="py-3 px-4 w-28 text-center">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                              isCompleted
                                ? 'bg-slate-100 text-slate-700 border-slate-200'
                                : 'bg-emerald-50 text-emerald-700 border-emerald-200/60'
                            }`}
                          >
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${
                                isCompleted ? 'bg-slate-500' : 'bg-emerald-500'
                              }`}
                            />
                            {status}
                          </span>
                        </td>
                        <td className="py-3 px-4 w-44 text-right shrink-0">
                          <div className="inline-flex items-center justify-end gap-1.5 shrink-0 min-w-[160px]" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => handleRequisitionClick(proj)}
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-colors shadow-2xs cursor-pointer border ${
                                isCompleted
                                  ? 'bg-slate-900 hover:bg-slate-800 text-white border-transparent'
                                  : 'bg-white hover:bg-slate-50 text-slate-800 border-slate-200 hover:border-slate-300'
                              }`}
                            >
                              {isCompleted ? <FileText size={13} /> : <ListOrdered size={13} />}
                              <span>{isCompleted ? 'View Reports' : 'View Rankings'}</span>
                            </button>
                            <div className="h-4 w-px bg-slate-200 mx-0.5" />
                            <button
                              type="button"
                              title={`Delete "${proj.title}"`}
                              aria-label={`Delete requisition ${proj.title}`}
                              onClick={(e) => handleDeleteClick(e, proj)}
                              disabled={deletingId === proj.id}
                              className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 border border-transparent hover:border-red-200 transition-colors cursor-pointer shrink-0 disabled:opacity-50"
                            >
                              {deletingId === proj.id ? (
                                <Loader2 size={13} className="animate-spin text-red-600 shrink-0" />
                              ) : (
                                <Trash2 size={13} className="shrink-0" />
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
                  Showing <strong className="text-slate-900 font-bold">{(effectivePage - 1) * PAGE_SIZE + 1}</strong> to{' '}
                  <strong className="text-slate-900 font-bold">
                    {Math.min(effectivePage * PAGE_SIZE, filteredProjects.length)}
                  </strong>{' '}
                  of <strong className="text-slate-900 font-bold">{filteredProjects.length}</strong> requisitions
                </p>

                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => updateUrlParams({ page: Math.max(1, effectivePage - 1) })}
                    disabled={effectivePage === 1}
                    className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    <ChevronLeft size={14} />
                  </button>

                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((pg) => (
                    <button
                      key={pg}
                      type="button"
                      onClick={() => updateUrlParams({ page: pg })}
                      className={`w-7 h-7 rounded-lg text-xs transition-colors cursor-pointer ${
                        effectivePage === pg
                          ? 'bg-slate-900 text-white font-bold shadow-2xs'
                          : 'text-slate-600 hover:bg-slate-100 font-medium'
                      }`}
                    >
                      {pg}
                    </button>
                  ))}

                  <button
                    type="button"
                    onClick={() => updateUrlParams({ page: Math.min(totalPages, effectivePage + 1) })}
                    disabled={effectivePage === totalPages}
                    className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
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
        <div
          className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !deletingId) {
              setConfirmDeleteProject(null)
              setDeleteError(null)
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-requisition-title"
            className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl border border-slate-200 space-y-4 animate-in fade-in zoom-in duration-150"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-red-50 text-red-600 flex items-center justify-center shrink-0 border border-red-100">
                  <Trash2 size={18} />
                </div>
                <div>
                  <h3 id="delete-requisition-title" className="text-base font-bold text-slate-900">
                    Delete Requisition
                  </h3>
                  <p className="text-xs text-slate-500">Destructive action · cannot be undone</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setConfirmDeleteProject(null)
                  setDeleteError(null)
                }}
                disabled={deletingId === confirmDeleteProject.id}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-50"
                aria-label="Close dialog"
              >
                <X size={16} />
              </button>
            </div>

            {/* Requisition Details Preview Card */}
            <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-lg space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Target Requisition</span>
                <span className="px-2 py-0.5 rounded-md bg-slate-200/70 text-slate-700 text-[10px] font-semibold font-mono">
                  {confirmDeleteProject.department || 'General'}
                </span>
              </div>
              <p className="text-xs font-bold text-slate-900 leading-snug break-words">
                {confirmDeleteProject.title}
              </p>
              {confirmDeleteProject.target_role && (
                <p className="text-[11px] text-slate-500 font-medium">
                  Role: <span className="text-slate-700 font-semibold">{confirmDeleteProject.target_role}</span>
                </p>
              )}
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to permanently delete this requisition? All candidate rankings, screening scores, and uploaded resume records associated with it will be permanently removed.
            </p>

            {deleteError && (
              <div className="p-3 bg-red-50 text-red-700 text-xs rounded-lg font-medium border border-red-200 flex items-center gap-2">
                <AlertCircle size={14} className="shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setConfirmDeleteProject(null)
                  setDeleteError(null)
                }}
                disabled={deletingId === confirmDeleteProject.id}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-50 border border-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deletingId === confirmDeleteProject.id}
                className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {deletingId === confirmDeleteProject.id ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <span>Delete Requisition</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete All Confirmation Modal */}
      {confirmDeleteAll && (
        <div
          className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !isDeletingAll) {
              setConfirmDeleteAll(false)
              setDeleteError(null)
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-all-dialog-title"
            className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl border border-slate-200 space-y-4 animate-in fade-in zoom-in duration-150"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-red-50 text-red-600 flex items-center justify-center shrink-0 border border-red-100">
                  <Trash2 size={18} />
                </div>
                <div>
                  <h3 id="delete-all-dialog-title" className="text-base font-bold text-slate-900">
                    Delete All Requisitions
                  </h3>
                  <p className="text-xs text-slate-500">Destructive action · cannot be undone</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setConfirmDeleteAll(false)
                  setDeleteError(null)
                }}
                disabled={isDeletingAll}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors disabled:opacity-50 cursor-pointer"
                aria-label="Close dialog"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to delete <strong className="text-slate-900">all {projects.length} {projects.length === 1 ? 'requisition' : 'requisitions'}</strong>? All associated screening scores, candidate rankings, and job description files will be permanently removed from the database.
            </p>

            {deleteError && (
              <div className="p-3 bg-red-50 text-red-700 text-xs rounded-lg font-medium border border-red-200 flex items-center gap-2">
                <AlertCircle size={14} className="shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setConfirmDeleteAll(false)
                  setDeleteError(null)
                }}
                disabled={isDeletingAll}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-50 cursor-pointer border border-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDeleteAll}
                disabled={isDeletingAll}
                className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer disabled:opacity-50"
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
