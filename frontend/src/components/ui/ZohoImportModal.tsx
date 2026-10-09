import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X,
  Search,
  Building2,
  MapPin,
  Sparkles,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Briefcase,
  Users,
  RefreshCw,
  ChevronRight,
  FileText,
} from 'lucide-react'
import { api, ZohoJobOpening, ZohoStatusResponse } from '@/api'

interface ZohoImportModalProps {
  isOpen: boolean
  onClose: () => void
  mode: 'jd' | 'applicants'
  onSelectJob: (job: ZohoJobOpening) => Promise<void>
  isProcessing?: boolean
  selectedJobId?: string
}

export default function ZohoImportModal({
  isOpen,
  onClose,
  mode,
  onSelectJob,
  isProcessing = false,
  selectedJobId,
}: ZohoImportModalProps) {
  const [status, setStatus] = useState<ZohoStatusResponse | null>(null)
  const [jobs, setJobs] = useState<ZohoJobOpening[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [previewJob, setPreviewJob] = useState<ZohoJobOpening | null>(null)

  const loadZohoData = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const statusRes = await api.getZohoStatus()
      setStatus(statusRes)

      if (statusRes.configured) {
        const jobsRes = await api.listZohoJobOpenings({ limit: 100 })
        setJobs(jobsRes.items)
      } else {
        setError('Zoho Recruit credentials are not configured in backend/.env.')
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to connect to Zoho Recruit API.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      loadZohoData()
    } else {
      setPreviewJob(null)
      setSearchQuery('')
    }
  }, [isOpen])

  if (!isOpen) return null

  const filteredJobs = jobs.filter((job) => {
    const matchesSearch =
      job.posting_title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (job.department && job.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (job.job_opening_id && job.job_opening_id.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (job.required_skills && job.required_skills.toLowerCase().includes(searchQuery.toLowerCase()))

    const matchesStatus =
      statusFilter === 'ALL' ||
      (statusFilter === 'OPEN' && (job.job_status?.toLowerCase().includes('in-progress') || job.job_status?.toLowerCase().includes('open'))) ||
      job.job_status?.toUpperCase() === statusFilter.toUpperCase()

    return matchesSearch && matchesStatus
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        transition={{ duration: 0.2 }}
        className="relative w-full max-w-4xl max-h-[88vh] flex flex-col bg-slate-900 border border-slate-700/70 rounded-2xl shadow-2xl overflow-hidden text-slate-100"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/60">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500/20 to-orange-500/20 border border-amber-500/30 text-amber-400">
              <Briefcase className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold tracking-tight text-white">
                  {mode === 'jd' ? 'Import Job Description from Zoho' : 'Sync Applicants from Zoho'}
                </h2>
                {status?.configured && (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Zoho Connected
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                {mode === 'jd'
                  ? 'Select a job opening to automatically import and extract the JD into this requisition.'
                  : 'Select the job opening to import all submitted candidate resumes into this project.'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isProcessing}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Toolbar & Filter */}
        <div className="p-4 border-b border-slate-800/80 bg-slate-900/50 flex flex-wrap items-center justify-between gap-3">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search by job title, ID, skills, department..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-950/70 border border-slate-700/80 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500 transition-all"
            />
          </div>

          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-slate-950/70 border border-slate-700/80 rounded-xl text-xs font-medium text-slate-200 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
            >
              <option value="ALL">All Statuses</option>
              <option value="OPEN">Open / In-progress</option>
              <option value="CLOSED">Closed</option>
            </select>

            <button
              onClick={loadZohoData}
              disabled={isLoading || isProcessing}
              title="Refresh list from Zoho"
              className="p-2 text-slate-400 hover:text-amber-400 hover:bg-slate-800 rounded-xl border border-slate-700/60 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-amber-400' : ''}`} />
            </button>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="m-4 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start gap-3 text-rose-300 text-xs">
            <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400" />
            <div className="flex-1">
              <p className="font-semibold text-rose-200">Zoho Integration Notice</p>
              <p className="mt-0.5 text-rose-300/90">{error}</p>
              <p className="mt-1 text-slate-400">
                Please verify that <code className="text-amber-300">ZOHO_CLIENT_ID</code>, <code className="text-amber-300">ZOHO_CLIENT_SECRET</code>, and tokens are set in <code className="text-slate-300">backend/.env</code>.
              </p>
            </div>
          </div>
        )}

        {/* Main Content Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-[300px]">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin text-amber-400 mb-3" />
              <p className="text-sm font-medium">Fetching Job Openings from Zoho Recruit...</p>
              <p className="text-xs text-slate-500 mt-1">Connecting to Zoho Recruit v2 API</p>
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center text-slate-400">
              <Briefcase className="w-10 h-10 text-slate-600 mb-3" />
              <p className="text-sm font-medium text-slate-300">No matching Zoho Job Openings found</p>
              <p className="text-xs text-slate-500 mt-1">
                {searchQuery ? 'Try clearing your search query or status filter.' : 'No active jobs found in your Zoho tenant.'}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredJobs.map((job) => {
                const isSelected = selectedJobId === job.id
                const isOpenStatus =
                  job.job_status?.toLowerCase().includes('in-progress') ||
                  job.job_status?.toLowerCase().includes('open')

                return (
                  <div
                    key={job.id}
                    className={`relative flex flex-col justify-between p-4 rounded-xl border transition-all duration-200 ${
                      isSelected
                        ? 'bg-amber-500/10 border-amber-500/50 shadow-lg shadow-amber-500/10'
                        : 'bg-slate-950/40 border-slate-800 hover:border-slate-700 hover:bg-slate-800/40'
                    }`}
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <h3 className="text-sm font-semibold text-slate-100 line-clamp-1 group-hover:text-amber-400">
                          {job.posting_title}
                        </h3>
                        <span
                          className={`flex-shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                            isOpenStatus
                              ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-400'
                              : 'bg-slate-800 border border-slate-700 text-slate-400'
                          }`}
                        >
                          {job.job_status || 'Open'}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400 mb-3">
                        {job.job_opening_id && (
                          <span className="font-mono text-[11px] text-amber-400/90 bg-amber-400/10 px-1.5 py-0.5 rounded">
                            {job.job_opening_id}
                          </span>
                        )}
                        {job.department && (
                          <span className="flex items-center gap-1">
                            <Building2 className="w-3 h-3 text-slate-500" />
                            {job.department}
                          </span>
                        )}
                        {job.city && (
                          <span className="flex items-center gap-1">
                            <MapPin className="w-3 h-3 text-slate-500" />
                            {job.city}
                          </span>
                        )}
                        {job.no_of_candidates_associated !== undefined && (
                          <span
                            className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium ${
                              job.no_of_candidates_associated > 0
                                ? 'bg-sky-500/10 border border-sky-500/20 text-sky-400'
                                : 'bg-slate-800/80 text-slate-500'
                            }`}
                          >
                            <Users className="w-3 h-3" />
                            {job.no_of_candidates_associated}{' '}
                            {job.no_of_candidates_associated === 1 ? 'applicant' : 'applicants'}
                          </span>
                        )}
                      </div>

                      {job.required_skills && (
                        <div className="mb-3">
                          <p className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1">
                            Skills:
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {job.required_skills
                              .split(/[,\n]/)
                              .map((s) => s.trim())
                              .filter(Boolean)
                              .slice(0, 4)
                              .map((skill, idx) => (
                                <span
                                  key={idx}
                                  className="px-2 py-0.5 bg-slate-800/80 border border-slate-700/60 rounded text-[11px] text-slate-300"
                                >
                                  {skill}
                                </span>
                              ))}
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between gap-2 mt-auto">
                      <button
                        type="button"
                        onClick={() => setPreviewJob(previewJob?.id === job.id ? null : job)}
                        className="text-xs text-slate-400 hover:text-slate-200 underline flex items-center gap-1"
                      >
                        <FileText className="w-3 h-3" />
                        {previewJob?.id === job.id ? 'Hide JD' : 'Preview JD'}
                      </button>

                      <button
                        type="button"
                        disabled={isProcessing}
                        onClick={() => onSelectJob(job)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all ${
                          isSelected
                            ? 'bg-amber-500 text-slate-950 hover:bg-amber-400'
                            : 'bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 hover:from-amber-400 hover:to-orange-400'
                        }`}
                      >
                        {isProcessing && selectedJobId === job.id ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            {mode === 'jd' ? 'Importing JD...' : 'Syncing Resumes...'}
                          </>
                        ) : (
                          <>
                            <Sparkles className="w-3.5 h-3.5" />
                            {mode === 'jd' ? 'Select & Import' : 'Import Applicants'}
                          </>
                        )}
                      </button>
                    </div>

                    {/* Expandable JD Preview */}
                    <AnimatePresence>
                      {previewJob?.id === job.id && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          className="mt-3 p-3 bg-slate-950/80 border border-slate-800 rounded-lg text-xs text-slate-300 space-y-2 max-h-48 overflow-y-auto"
                        >
                          <p className="font-semibold text-amber-400">Full Job Description:</p>
                          <p className="whitespace-pre-wrap text-slate-300 leading-relaxed">
                            {job.job_description || 'No description text provided in Zoho Recruit.'}
                          </p>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-slate-800 bg-slate-950/80 text-xs text-slate-400">
          <span>Found {filteredJobs.length} job openings</span>
          <button
            onClick={onClose}
            disabled={isProcessing}
            className="px-4 py-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-300 transition-colors"
          >
            Close
          </button>
        </div>
      </motion.div>
    </div>
  )
}
