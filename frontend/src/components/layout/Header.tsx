import { motion } from 'framer-motion'
import { useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, UserRound, ChevronRight } from 'lucide-react'
import { usePipeline } from '@/store/pipelineStore'
import { DEPARTMENTS } from '@/constants/departments'

interface BreadcrumbItem {
  label: string
  href?: string
}

const PAGE_LABEL_MAP: Record<string, string> = {
  resumes: 'Resume Upload',
  rankings: 'Candidate Ranking',
  shortlist: 'Shortlisted Talent',
  assessment: 'Assessment Handoff',
  reports: 'Reports',
  new: 'Create Requisition',
}

export default function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const { state } = usePipeline()

  // Build dynamic breadcrumb items based on current location
  const getBreadcrumbs = (): BreadcrumbItem[] => {
    const items: BreadcrumbItem[] = [
      { label: 'Dashboard', href: '/dashboard' }
    ]

    const path = location.pathname

    if (path === '/dashboard') {
      const searchParams = new URLSearchParams(location.search)
      const dept = searchParams.get('dept')
      if (dept && dept !== 'ALL') {
        items.push({ label: 'Departments', href: '/departments' })
        items.push({ label: dept })
      }
      return items
    }

    if (path === '/departments') {
      items.push({ label: 'Departments' })
      return items
    }

    if (path === '/settings') {
      items.push({ label: 'Settings' })
      return items
    }

    if (path.startsWith('/departments/')) {
      const parts = path.split('/').filter(Boolean)
      const deptId = parts[1]
      const dept = DEPARTMENTS.find(
        (d) =>
          d.id.toLowerCase() === deptId?.toLowerCase() ||
          d.name.toLowerCase() === deptId?.toLowerCase() ||
          d.code.toLowerCase() === deptId?.toLowerCase()
      ) || DEPARTMENTS[0]
      const deptName = dept?.name || 'Department'

      items.push({ label: 'Departments', href: '/departments' })

      if (parts.length === 2) {
        items.push({ label: deptName })
      } else if (parts.length > 2 && parts[2] === 'requisitions' && parts[3] === 'new') {
        items.push({ label: deptName, href: `/dashboard?dept=${encodeURIComponent(deptName)}` })
        items.push({ label: 'Create Requisition' })
      }
      return items
    }

    if (path.startsWith('/projects')) {
      const parts = path.split('/').filter(Boolean)
      
      if (parts.length === 1) {
        items.push({ label: 'Requisitions' })
        return items
      }

      if (parts[1] === 'new') {
        items.push({ label: 'Create Requisition' })
        return items
      }

      const projectId = parts[1]
      const subPage = parts[2] || 'overview'

      // Resolve department for project
      const activeDept = DEPARTMENTS.find(
        (d) =>
          d.id === state.activeDepartmentId ||
          d.name.toLowerCase() === state.selectedProject?.department?.toLowerCase() ||
          d.code.toLowerCase() === state.selectedProject?.department?.toLowerCase()
      ) || DEPARTMENTS[0]

      items.push({
        label: activeDept.name,
        href: `/dashboard?dept=${encodeURIComponent(activeDept.name)}`,
      })

      const projectTitle = state.selectedProject?.title || 'Requisition'

      if (subPage === 'rankings') {
        items.push({ label: projectTitle })
      } else {
        items.push({
          label: projectTitle,
          href: `/projects/${projectId}/rankings`,
        })
        const subLabel = PAGE_LABEL_MAP[subPage] || subPage.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
        items.push({ label: subLabel })
      }
      return items
    }

    const fallbackLabel = path.split('/').pop()?.replace(/-/g, ' ') || 'Page'
    items.push({ label: fallbackLabel.replace(/\b\w/g, (l) => l.toUpperCase()) })
    return items
  }

  const breadcrumbs = getBreadcrumbs()

  return (
    <motion.header
      className="app-header px-6"
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      {/* ── Breadcrumb Hierarchy ── */}
      <div className="flex items-center gap-2 flex-1 min-w-0 overflow-x-auto py-1 scrollbar-none">
        {breadcrumbs.map((item, index) => {
          const isLast = index === breadcrumbs.length - 1
          return (
            <div key={index} className="flex items-center gap-2 shrink-0 text-[12px]">
              {index === 0 && <LayoutDashboard size={14} className="text-slate-400 shrink-0 mr-0.5" />}
              
              {!isLast && item.href ? (
                <button
                  type="button"
                  onClick={() => navigate(item.href!)}
                  className="font-medium text-slate-500 hover:text-blue-600 transition-colors cursor-pointer truncate max-w-[180px]"
                  title={item.label}
                >
                  {item.label}
                </button>
              ) : !isLast ? (
                <span className="font-medium text-slate-500 truncate max-w-[180px]">{item.label}</span>
              ) : (
                <span className="font-extrabold text-slate-900 truncate max-w-[220px]" title={item.label}>
                  {item.label}
                </span>
              )}

              {!isLast && <ChevronRight size={13} className="text-slate-300 shrink-0" />}
            </div>
          )
        })}
      </div>

      {/* ── Right Controls ── */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-600">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-600">
            <UserRound size={15} />
          </span>
          <span className="hidden sm:inline">Recruiter</span>
        </div>
      </div>
    </motion.header>
  )
}
