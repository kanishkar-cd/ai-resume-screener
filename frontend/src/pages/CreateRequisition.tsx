import { useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  FileText,
  Upload,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  Building2,
  AlertCircle,
  SlidersHorizontal,
  Cpu,
  GraduationCap,
  Briefcase,
  ListChecks,
  Info,
  Loader2,
} from 'lucide-react'
import { DEPARTMENTS } from '@/constants/departments'
import { usePipeline } from '@/store/pipelineStore'
import { api, ApiError, ExtractedJobDescription } from '@/api'

// ─── Step labels ──────────────────────────────────────────────────────────────
const STEP_LABELS = [
  'Basic Information',
  'Upload JD',
  'Screening Criteria',
  'Review & Start',
]

const INVALID_STANDALONE_SKILLS = new Set([
  'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as',
  'into', 'through', 'during', 'including', 'is', 'was', 'are', 'were', 'be', 'been', 'being', 'am',
  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'shall', 'can',
  'need', 'this', 'that', 'these', 'those', 'it', 'its', 'we', 'you', 'they', 'their', 'our', 'your',
  'who', 'what', 'which', 'when', 'where', 'how', 'if', 'then', 'than', 'so', 'not', 'no', 'nor', 'yet',
  'both', 'either', 'each', 'any', 'all', 'most', 'more', 'such', 'up', 'about', 'etc', 'eg', 'ie', 'via',
  'skills', 'skill', 'basis', 'basics', 'basic', 'requirements', 'requirement', 'required', 'qualifications',
  'qualification', 'qualify', 'responsibilities', 'responsibility', 'duties', 'duty', 'knowledge',
  'experience', 'understanding', 'proficiency', 'proficient', 'exposure', 'familiarity', 'concepts', 'concept',
  'fundamentals', 'fundamental', 'principles', 'principle', 'tools', 'tool', 'technologies', 'technology',
  'methods', 'method', 'methodologies', 'methodology', 'systems', 'system', 'frameworks', 'framework',
  'languages', 'language', 'applications', 'application', 'solutions', 'solution', 'practices', 'practice',
  'standards', 'standard', 'capabilities', 'capability', 'competencies', 'competency', 'abilities', 'ability',
  'plus', 'bonus', 'advantage', 'advantageous', 'preferred', 'desirable', 'desired', 'optional', 'mandatory',
  'overview', 'summary', 'description', 'details', 'candidate', 'candidates', 'role', 'roles', 'position',
  'positions', 'job', 'jobs', 'work', 'working', 'team', 'teams', 'level', 'levels', 'year', 'years', 'month', 'months',
  'good', 'strong', 'solid', 'deep', 'excellent', 'proven', 'sound', 'hands-on', 'handson',
  'active', 'inactive', 'log', 'logs', 'analysis', 'analytics',
  'triage', 'findings', 'policies', 'procedures',
])

function isValidSkill(skill: string): boolean {
  if (!skill || typeof skill !== 'string') return false
  const cleaned = skill.trim()
  if (cleaned.length < 2 && !['C', 'R'].includes(cleaned.toUpperCase())) return false
  if (cleaned.length > 60) return false
  if (!/[a-zA-Z]/.test(cleaned)) return false
  const lower = cleaned.toLowerCase()
  if (INVALID_STANDALONE_SKILLS.has(lower)) return false
  const words = cleaned.split(/\s+/)
  if (words.length === 1 && INVALID_STANDALONE_SKILLS.has(lower)) return false
  return true
}

export default function CreateRequisition() {
  const { deptId } = useParams<{ deptId: string }>()
  const navigate = useNavigate()
  const { dispatch } = usePipeline()

  const department = DEPARTMENTS.find((d) => d.id === deptId) || DEPARTMENTS[0]

  // Form State
  const [currentStep, setCurrentStep] = useState(1)
  const [jobTitle, setJobTitle] = useState('')
  const [expLevel, setExpLevel] = useState<'Experienced' | 'Fresher'>('Fresher')
  const [reqRef] = useState(() => `REQ-2026-${department.code}-${Math.floor(100 + Math.random() * 900)}`)

  // JD Upload State
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [isProcessingJd, setIsProcessingJd] = useState(false)
  const [processingStatusMessage, setProcessingStatusMessage] = useState('Reading JD data')
  const [jdError, setJdError] = useState<string | null>(null)
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null)
  const [extractedJd, setExtractedJd] = useState<ExtractedJobDescription | null>(null)

  // In-flight and cached processing refs
  const inFlightPromiseRef = useRef<Promise<void> | null>(null)
  const processedFileRef = useRef<File | null>(null)
  const extractedJdRef = useRef<ExtractedJobDescription | null>(null)
  const projectIdRef = useRef<string | null>(null)

  // Threshold State — weights are kept for backend compatibility but not shown in UI
  const [passingScore, setPassingScore] = useState(30.0)
  const [showAllResponsibilities, setShowAllResponsibilities] = useState(false)

  // Default weights sent to backend unchanged (hidden from UI per product decision)
  const defaultWeights = { skills: 40, projects: 40, education: 10, certifications: 5, languages: 5, experience: 0 }

  // Background JD upload, parse, extract, and normalize pipeline
  const startJdProcessing = useCallback((file: File) => {
    // If already processed for this file, return existing resolution
    if (processedFileRef.current === file && extractedJdRef.current) {
      return Promise.resolve()
    }

    // If an in-flight promise is already running for this file, return it
    if (inFlightPromiseRef.current) {
      return inFlightPromiseRef.current
    }

    setIsProcessingJd(true)
    setJdError(null)
    setProcessingStatusMessage('Reading JD data')

    const promise = (async () => {
      try {
        let projId = projectIdRef.current || createdProjectId
        if (!projId) {
          const safeRole = jobTitle.trim() || `${department.name} Role`
          const safeTitle = jobTitle.trim() ? `${reqRef} - ${jobTitle.trim()}` : `${reqRef} - ${department.name}`
          const proj = await api.createProject({
            title: safeTitle,
            target_role: safeRole,
            department: department.name || 'General',
            description: `Requisition ${reqRef} for ${expLevel} level HR screening`,
            metadata_json: { experience_level: expLevel, req_ref: reqRef },
            status: 'DRAFT',
          })
          projId = proj.id
          projectIdRef.current = projId
          setCreatedProjectId(projId)
          dispatch({
            type: 'SELECT_PROJECT',
            payload: {
              id: proj.id,
              title: proj.title,
              target_role: proj.target_role,
              department: proj.department,
              description: proj.description,
              status: proj.status,
              metadata_json: proj.metadata_json,
              created_at: proj.created_at,

              updated_at: proj.updated_at,
            },
          })
        }

        // Upload & Parse
        const uploadRes = await api.uploadJobDescription(projId, file)
        const docId = uploadRes.document_id
        dispatch({ type: 'SET_JD_DOCUMENT_ID', payload: docId })

        await api.parseDocument(docId)

        // Extract
        setProcessingStatusMessage('Analyzing job requirements')
        await api.extractDocument(docId)

        // Normalize
        setProcessingStatusMessage('Preparing screening criteria')
        await api.normalizeDocument(docId)
        dispatch({
          type: 'SET_JD_PROCESSING',
          payload: { status: 'COMPLETED', stage: 'COMPLETED', normalized: true },
        })

        // Fetch actual extracted JSON
        setProcessingStatusMessage('Almost ready')
        try {
          const ext = await api.getExtractedDocument(docId)
          if ('required_skills' in ext || 'skills' in ext) {
            setExtractedJd(ext as ExtractedJobDescription)
            extractedJdRef.current = ext as ExtractedJobDescription
          }
        } catch {
          // Extraction data optional fallback
        }

        setProcessingStatusMessage('Almost ready')
        processedFileRef.current = file
      } catch (err) {
        processedFileRef.current = null
        extractedJdRef.current = null
        const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Failed to process Job Description'
        setJdError(msg)
        throw err
      } finally {
        inFlightPromiseRef.current = null
        setIsProcessingJd(false)
      }
    })()

    inFlightPromiseRef.current = promise
    return promise
  }, [createdProjectId, reqRef, jobTitle, department.name, expLevel, dispatch])

  const handleFileChange = (file: File) => {
    if (processedFileRef.current !== file) {
      processedFileRef.current = null
      extractedJdRef.current = null
      setExtractedJd(null)
    }
    setJdFile(file)
    setJdError(null)
    // Non-blocking background processing starts as soon as the file is selected
    startJdProcessing(file).catch(() => {
      // Error is caught and surfaced in jdError state
    })
  }

  // Step 2 → Step 3: Navigate immediately to screening criteria without blocking
  const handleProceedToStep3 = () => {
    if (!jdFile) return
    setCurrentStep(3)
    if (!processedFileRef.current || processedFileRef.current !== jdFile) {
      startJdProcessing(jdFile).catch(() => {})
    }
  }

  // Step 3 → Step 4: just advance
  const handleContinueToReview = () => {
    setCurrentStep(4)
  }

  // Step 4 → Start Screening: ensure project created + persist threshold, then navigate
  const handleStartScreening = async () => {
    setIsProcessingJd(true)
    setJdError(null)

    try {
      let targetProjId = createdProjectId

      // Fallback: If project was not created in earlier steps, create it now
      if (!targetProjId) {
        const safeRole = jobTitle.trim() || `${department.name} Role`
        const safeTitle = jobTitle.trim() ? `${reqRef} - ${jobTitle.trim()}` : `${reqRef} - ${department.name}`
        const proj = await api.createProject({
          title: safeTitle,
          target_role: safeRole,
          department: department.name || 'General',
          description: `Requisition ${reqRef} for ${expLevel} level HR screening`,
          metadata_json: { experience_level: expLevel, req_ref: reqRef },
          status: 'DRAFT',
        })
        targetProjId = proj.id
        setCreatedProjectId(targetProjId)
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

        if (jdFile) {
          try {
            const uploadRes = await api.uploadJobDescription(targetProjId, jdFile)
            await api.parseDocument(uploadRes.document_id)
            await api.extractDocument(uploadRes.document_id)
          } catch {
            // JD upload fallback
          }
        }
      }

      // Persist threshold + default weights to backend (try POST first, fallback to PATCH)
      try {
        await api.createWeightConfig(targetProjId, {
          passing_score: passingScore,
          weights: defaultWeights,
          min_experience_years: expLevel === 'Fresher' ? 0 : 1,
          mandatory_skills: [],
          preferred_skills: [],
          knockout_rules: [],
          custom_keywords: [],
        })
      } catch {
        try {
          await api.updateWeightConfig(targetProjId, {
            passing_score: passingScore,
            weights: defaultWeights,
          })
        } catch {
          // Weight config backend persistence non-blocking fallback
        }
      }

      navigate(`/projects/${targetProjId}/resumes`)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Failed to finalize requisition setup'
      setJdError(msg)
    } finally {
      setIsProcessingJd(false)
    }
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
        <button
          type="button"
          onClick={() => navigate(`/departments/${department.id}`)}
          className="hover:text-blue-600 transition-colors"
        >
          {department.name}
        </button>
        <span>/</span>
        <span className="text-slate-900 font-bold">New Requisition</span>
      </div>

      {/* Title Header */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex items-center justify-between">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-semibold mb-2">
            <Building2 size={13} />
            {department.name} Requisition
          </div>
          <h1 className="text-xl font-extrabold text-slate-900">Create Requisition</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {STEP_LABELS[currentStep - 1]}
            {currentStep < 4 && (
              <span className="ml-1 text-slate-400">— Step {currentStep} of 4</span>
            )}
          </p>
        </div>

        {/* Stepper */}
        <div className="flex items-center gap-3">
          {[1, 2, 3, 4].map((step) => (
            <div key={step} className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                  currentStep === step
                    ? 'bg-blue-600 text-white ring-4 ring-blue-100'
                    : currentStep > step
                    ? 'bg-emerald-500 text-white'
                    : 'bg-slate-100 text-slate-400'
                }`}
              >
                {currentStep > step ? <CheckCircle2 size={16} /> : step}
              </div>
              {step < 4 && <div className="w-6 h-[2px] bg-slate-200" />}
            </div>
          ))}
        </div>
      </div>

      {/* Step Content */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-8 shadow-sm">

        {/* ── Step 1: Basic Information ── */}
        {currentStep === 1 && (
          <div className="space-y-6">
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <FileText size={18} className="text-blue-600" />
              1. Basic Information
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="md:col-span-2">
                <label className="block text-xs font-bold text-slate-700 uppercase mb-2">
                  Job Title <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  placeholder="e.g. Full-Stack Software Engineer"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-2">
                  Experience Level
                </label>
                <div className="grid grid-cols-2 gap-3">
                  {(['Fresher', 'Experienced'] as const).map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      onClick={() => setExpLevel(lvl)}
                      className={`py-2.5 px-4 rounded-xl text-xs font-bold border transition-all ${
                        expLevel === lvl
                          ? 'bg-blue-50 border-blue-500 text-blue-700 shadow-sm'
                          : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>

              <div className="md:col-span-2 p-3.5 bg-slate-50 border border-slate-200/80 rounded-xl flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 text-slate-500">
                  <Info size={14} className="text-blue-600 shrink-0" />
                  <span className="font-medium">Auto-generated Requisition ID:</span>
                </div>
                <span className="font-mono font-bold text-slate-800 bg-white px-2.5 py-1 rounded-md border border-slate-200/80">
                  {reqRef}
                </span>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-100 flex justify-end">
              <button
                type="button"
                onClick={() => setCurrentStep(2)}
                disabled={!jobTitle.trim()}
                className="inline-flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                Next: Upload JD
                <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Upload JD ── */}
        {currentStep === 2 && (
          <div className="space-y-6">
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Upload size={18} className="text-blue-600" />
              2. Upload Job Description
            </h2>

            <div className="border-2 border-dashed border-slate-200 hover:border-blue-400 rounded-2xl p-10 text-center bg-slate-50/50 transition-all">
              <Upload size={32} className="mx-auto text-blue-500 mb-3" />
              <p className="text-sm font-bold text-slate-900">Upload Job Description Document</p>
              <p className="text-xs text-slate-400 mt-1">Supports PDF, DOCX, TXT formats (Max 10MB)</p>

              <input
                type="file"
                id="jd-upload"
                accept=".pdf,.docx,.txt"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    handleFileChange(e.target.files[0])
                  }
                }}
                className="hidden"
              />
              <label
                htmlFor="jd-upload"
                className="inline-block mt-4 px-5 py-2 bg-white border border-slate-200 text-slate-700 text-xs font-bold rounded-xl shadow-sm hover:bg-slate-50 cursor-pointer"
              >
                Choose File
              </label>

              {jdFile && (
                <div className="mt-4 p-3 bg-blue-50 text-blue-700 rounded-xl text-xs font-bold inline-flex items-center gap-2">
                  <FileText size={15} />
                  <span>{jdFile.name}</span>
                </div>
              )}

              {jdError && (
                <div className="mt-4 p-3 bg-red-50 text-red-700 text-xs rounded-xl font-medium border border-red-200/80 flex items-center gap-2 text-left">
                  <AlertCircle size={14} className="shrink-0" />
                  <span>{jdError}</span>
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-slate-100 flex justify-between">
              <button
                type="button"
                onClick={() => setCurrentStep(1)}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                <ArrowLeft size={15} />
                Back
              </button>
              <button
                type="button"
                onClick={handleProceedToStep3}
                disabled={!jdFile}
                className="inline-flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                <span>Next: Screening Criteria</span>
                <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Screening Criteria ── */}
        {currentStep === 3 && (
          <div className="space-y-6">

            {/* ─ Recommendation Threshold (Always visible) ─ */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-slate-900">Screening Threshold</h4>
                  <p className="text-xs text-slate-500 mt-0.5">Minimum score for a candidate to be recommended</p>
                </div>
                <span className="px-5 py-2 bg-blue-600 text-white rounded-xl font-extrabold text-base shadow-sm tabular-nums min-w-[70px] text-center">
                  {passingScore.toFixed(0)}<span className="text-xs font-semibold opacity-70"> / 100</span>
                </span>
              </div>
              <input
                type="range"
                min="10"
                max="90"
                step="5"
                value={passingScore}
                onChange={(e) => setPassingScore(parseFloat(e.target.value))}
                className="w-full h-2 bg-slate-100 rounded-full appearance-none cursor-pointer accent-blue-600"
              />
              <div className="flex justify-between text-[10px] font-semibold text-slate-400">
                <span>10 · Open</span>
                <span>30 · Default</span>
                <span>60 · Selective</span>
                <span>90 · Strict</span>
              </div>
            </div>

            {/* ─ JD Requirements Section / Processing Status ─ */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Extracted JD Requirements</h4>
                <span className="text-[10px] font-semibold px-2 py-0.5 bg-blue-50 text-blue-600 rounded-full border border-blue-100">
                  {expLevel} screening mode
                </span>
              </div>

              {isProcessingJd ? (
                <div className="py-10 px-6 bg-slate-50/60 border border-slate-200/80 rounded-2xl text-center space-y-4 animate-in fade-in duration-150">
                  <div
                    className={`w-11 h-11 rounded-xl flex items-center justify-center mx-auto shadow-xs transition-colors ${
                      processingStatusMessage === 'Almost ready'
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-200/60'
                        : 'bg-blue-50 text-blue-600'
                    }`}
                  >
                    {processingStatusMessage === 'Almost ready' ? (
                      <CheckCircle2 size={22} className="text-emerald-600" />
                    ) : (
                      <Loader2 size={22} className="animate-spin text-blue-600" />
                    )}
                  </div>
                  <div className="space-y-1 max-w-sm mx-auto">
                    <h3 className="text-sm font-bold text-slate-900">Preparing Screening Criteria</h3>
                    <p className="text-xs text-slate-500">Extracting structured role requirements from your Job Description</p>
                  </div>
                  <div className="max-w-xs mx-auto pt-1">
                    <div
                      className={`inline-flex items-center gap-2 text-xs font-bold px-3.5 py-1.5 rounded-xl shadow-xs border transition-colors ${
                        processingStatusMessage === 'Almost ready'
                          ? 'text-emerald-700 bg-emerald-50/90 border-emerald-200/80'
                          : 'text-blue-700 bg-blue-50/90 border-blue-200/80'
                      }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full ${
                          processingStatusMessage === 'Almost ready'
                            ? 'bg-emerald-500'
                            : 'bg-blue-600 animate-pulse'
                        }`}
                      />
                      <span>{processingStatusMessage}</span>
                    </div>
                  </div>
                </div>
              ) : jdError ? (
                <div className="p-6 bg-red-50/80 border border-red-200/80 rounded-2xl text-center space-y-3 animate-in fade-in duration-150">
                  <div className="w-10 h-10 rounded-xl bg-red-100 text-red-600 flex items-center justify-center mx-auto shadow-xs">
                    <AlertCircle size={20} />
                  </div>
                  <div className="space-y-1 max-w-md mx-auto">
                    <h4 className="text-xs font-bold text-slate-900">Failed to extract screening criteria</h4>
                    <p className="text-xs text-red-600 leading-relaxed">{jdError}</p>
                  </div>
                  <div className="flex items-center justify-center gap-3 pt-1">
                    <button
                      type="button"
                      onClick={() => setCurrentStep(2)}
                      className="px-3.5 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-50 transition-colors cursor-pointer"
                    >
                      Back to Upload
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (jdFile) {
                          setJdError(null)
                          startJdProcessing(jdFile).catch(() => {})
                        }
                      }}
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 transition-colors cursor-pointer"
                    >
                      Retry
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {/* Experience */}
                  <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-start gap-3">
                    <Briefcase size={15} className="text-amber-500 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">Experience</p>
                      <p className="text-xs font-semibold text-slate-800">
                        {extractedJd?.experience && extractedJd.experience.length > 0
                          ? extractedJd.experience.join(' · ')
                          : 'Not specified in JD'}
                      </p>
                    </div>
                  </div>

                  {/* Education & Disciplines */}
                  {((extractedJd?.education && extractedJd.education.length > 0) ||
                    (extractedJd?.education_disciplines && extractedJd.education_disciplines.length > 0)) && (
                    <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-start gap-3">
                      <GraduationCap size={15} className="text-purple-500 shrink-0 mt-0.5" />
                      <div className="space-y-1.5 w-full">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Education</p>
                        {extractedJd?.education && extractedJd.education.length > 0 && (
                          <p className="text-xs font-semibold text-slate-800">{extractedJd.education.join(', ')}</p>
                        )}
                        {extractedJd?.education_disciplines && extractedJd.education_disciplines.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {extractedJd.education_disciplines.map((d) => (
                              <span key={d} className="px-2.5 py-0.5 rounded-full bg-purple-50 text-purple-700 text-[10px] font-bold border border-purple-100">{d}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Required Skills */}
                  {((extractedJd?.required_skills && extractedJd.required_skills.length > 0) ||
                    (extractedJd?.skills && extractedJd.skills.length > 0)) && (
                    <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-start gap-3">
                      <Cpu size={15} className="text-blue-500 shrink-0 mt-0.5" />
                      <div className="space-y-1.5 w-full">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Required Skills</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(extractedJd?.required_skills?.length
                            ? extractedJd.required_skills
                            : extractedJd?.skills || []
                          )
                            .filter(isValidSkill)
                            .map((s) => (
                              <span key={s} className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-bold border border-blue-100">{s}</span>
                            ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Preferred Skills */}
                  {extractedJd?.preferred_skills && extractedJd.preferred_skills.filter(isValidSkill).length > 0 && (
                    <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-start gap-3">
                      <SlidersHorizontal size={15} className="text-indigo-400 shrink-0 mt-0.5" />
                      <div className="space-y-1.5 w-full">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Preferred Skills</p>
                        <div className="flex flex-wrap gap-1.5">
                          {extractedJd.preferred_skills.filter(isValidSkill).map((ps) => (
                            <span key={ps} className="px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-600 text-[10px] font-bold border border-indigo-100">{ps}</span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Role Responsibilities */}
                  <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-start gap-3">
                    <ListChecks size={15} className="text-emerald-500 shrink-0 mt-0.5" />
                    <div className="space-y-1.5 w-full">
                      <div className="flex items-center justify-between">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Role Responsibilities</p>
                        {extractedJd?.responsibilities && extractedJd.responsibilities.length > 3 && (
                          <button
                            type="button"
                            onClick={() => setShowAllResponsibilities((v) => !v)}
                            className="text-[10px] font-bold text-blue-600 hover:text-blue-800 transition-colors"
                          >
                            {showAllResponsibilities ? 'Show less ↑' : `+${extractedJd.responsibilities.length - 3} more ↓`}
                          </button>
                        )}
                      </div>
                      {extractedJd?.responsibilities && extractedJd.responsibilities.length > 0 ? (
                        <ul className="space-y-1">
                          {(showAllResponsibilities
                            ? extractedJd.responsibilities
                            : extractedJd.responsibilities.slice(0, 3)
                          ).map((r) => (
                            <li key={r} className="flex items-start gap-2 text-xs text-slate-600">
                              <span className="w-1 h-1 rounded-full bg-emerald-400 shrink-0 mt-1.5" />
                              {r}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs font-semibold text-slate-500 italic">Not specified in JD</p>
                      )}
                    </div>
                  </div>

                  {/* Empty state */}
                  {(!extractedJd ||
                    (!extractedJd.education?.length &&
                      !extractedJd.required_skills?.length &&
                      !extractedJd.skills?.length &&
                      !extractedJd.preferred_skills?.length &&
                      !extractedJd.responsibilities?.length)) && (
                    <div className="p-5 bg-slate-50 border border-dashed border-slate-200 rounded-xl text-center space-y-1">
                      <p className="text-xs font-semibold text-slate-600">No structured requirements extracted from JD</p>
                      <p className="text-[11px] text-slate-400">The screening engine will evaluate candidates against the full JD text.</p>
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="pt-4 border-t border-slate-100 flex justify-between">
              <button
                type="button"
                onClick={() => setCurrentStep(2)}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                <ArrowLeft size={15} />
                Back
              </button>
              <button
                type="button"
                onClick={handleContinueToReview}
                disabled={isProcessingJd || Boolean(jdError)}
                className="inline-flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                Continue to Review
                <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Review & Start ── */}
        {currentStep === 4 && (
          <div className="space-y-6 py-4 max-w-xl mx-auto">
            <div className="text-center space-y-2">
              <div className="w-14 h-14 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mx-auto shadow-sm">
                <CheckCircle2 size={32} />
              </div>
              <h2 className="text-xl font-extrabold text-slate-900">Review & Confirm</h2>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                Verify the requisition details and 50+50 scoring model, then click <span className="font-bold text-slate-800">Upload Candidate Resumes</span> to begin screening.
              </p>
            </div>

            {/* Requisition Summary Card */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 text-left space-y-3 text-xs shadow-sm">
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">Requisition Overview</h4>
              
              <div className="grid grid-cols-2 gap-y-2.5 gap-x-4 border-b border-slate-100 pb-3">
                <div>
                  <span className="text-slate-400 text-[11px]">Department</span>
                  <p className="font-bold text-slate-900 mt-0.5">{department.name}</p>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px]">Job Title</span>
                  <p className="font-bold text-slate-900 mt-0.5">{jobTitle}</p>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px]">Experience Level</span>
                  <p className="font-bold text-slate-900 mt-0.5">{expLevel}</p>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px]">Requisition Reference</span>
                  <p className="font-bold font-mono text-slate-900 mt-0.5">{reqRef}</p>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px]">Job Description File</span>
                  <p className="font-bold text-slate-900 truncate mt-0.5">{jdFile ? jdFile.name : 'Uploaded'}</p>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px]">Recommendation Threshold</span>
                  <p className="font-bold text-blue-600 mt-0.5">{passingScore.toFixed(0)} / 100</p>
                </div>
              </div>

              {/* 50 + 50 Scoring Model Box */}
              <div className="space-y-2 pt-1">
                <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Evaluation Scoring Engine</h4>
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2">
                  <div className="flex items-center justify-between font-semibold text-slate-800">
                    <span className="flex items-center gap-2">
                      <Cpu size={14} className="text-blue-500" />
                      Deterministic Skills Match
                    </span>
                    <span className="px-2.5 py-0.5 rounded-md bg-blue-100 text-blue-700 font-bold text-[11px]">50 Marks</span>
                  </div>
                  <div className="flex items-center justify-between font-semibold text-slate-800">
                    <span className="flex items-center gap-2">
                      <SlidersHorizontal size={14} className="text-emerald-500" />
                      AI JD Relevance & Evidence
                    </span>
                    <span className="px-2.5 py-0.5 rounded-md bg-emerald-100 text-emerald-700 font-bold text-[11px]">50 Marks</span>
                  </div>
                  <div className="pt-2 border-t border-slate-200/80 flex items-center justify-between font-bold text-slate-900">
                    <span>Total Candidate Score</span>
                    <span className="text-blue-600 font-extrabold">100 Marks Max</span>
                  </div>
                </div>
              </div>
            </div>

            {jdError && (
              <div className="p-3.5 bg-red-50 text-red-700 rounded-xl text-xs font-semibold flex items-center gap-2 text-left">
                <AlertCircle size={15} className="shrink-0" />
                <span>{jdError}</span>
              </div>
            )}

            <div className="flex justify-between items-center pt-2">
              <button
                type="button"
                onClick={() => setCurrentStep(3)}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-200"
              >
                <ArrowLeft size={15} />
                Back
              </button>

              <button
                type="button"
                onClick={() => void handleStartScreening()}
                disabled={isProcessingJd}
                className="inline-flex items-center gap-2 px-7 py-3 bg-blue-600 text-white rounded-xl text-xs font-extrabold hover:bg-blue-700 transition-colors shadow-md disabled:opacity-60 cursor-pointer"
              >
                {isProcessingJd ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span>Finalizing Requisition...</span>
                  </>
                ) : (
                  <>
                    <span>Upload Candidate Resumes</span>
                    <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
