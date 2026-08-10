import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FileSearch, CheckCircle2, Clock, AlertCircle, ArrowRight, User, Briefcase, GraduationCap, Award, type LucideIcon } from 'lucide-react'
import StepIndicator from '@/components/ui/StepIndicator'
import { usePipeline } from '@/store/pipelineStore'
import { useNavigate } from 'react-router-dom'

const fadeUp = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }
const container = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }

type ExtractionStatus = 'pending' | 'running' | 'done' | 'error'

interface ExtractionField {
  id: string
  label: string
  icon: LucideIcon
  status: ExtractionStatus
  result?: string
}

const INITIAL_FIELDS: ExtractionField[] = [
  { id: 'name', label: 'Candidate Name', icon: User, status: 'pending' },
  { id: 'experience', label: 'Work Experience', icon: Briefcase, status: 'pending' },
  { id: 'education', label: 'Education History', icon: GraduationCap, status: 'pending' },
  { id: 'skills', label: 'Technical Skills', icon: CheckCircle2, status: 'pending' },
  { id: 'certifications', label: 'Certifications', icon: Award, status: 'pending' },
]

const RESULTS: Record<string, string> = {
  name: 'Candidate records from uploaded resumes',
  experience: '2–8 years (avg. 5.2 years)',
  education: "B.Sc CS × 3, M.Sc ML × 1",
  skills: 'Python, React, SQL, AWS, Docker, FastAPI...',
  certifications: 'AWS SA, GCP ACE, CKA...',
}

export default function InformationExtraction() {
  const { state, dispatch, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()
  const [fields, setFields] = useState<ExtractionField[]>(INITIAL_FIELDS)
  const [isRunning, setIsRunning] = useState(false)
  const [isDone, setIsDone] = useState(false)

  const totalResumes = state.upload.resumes.length || 4

  const runExtraction = async () => {
    setIsRunning(true)
    setFields((f) => f.map((x) => ({ ...x, status: 'pending' })))

    for (let i = 0; i < INITIAL_FIELDS.length; i++) {
      await new Promise((r) => setTimeout(r, 700 + i * 300))
      setFields((prev) =>
        prev.map((x, idx) =>
          idx === i
            ? { ...x, status: 'done', result: RESULTS[x.id] }
            : idx < i
            ? x
            : { ...x, status: idx === i + 1 ? 'running' : 'pending' }
        )
      )
    }
    setIsRunning(false)
    setIsDone(true)
  }

  const handleContinue = () => {
    completeAndAdvance()
    navigate('/normalization')
  }

  const statusIcon = (status: ExtractionStatus) => {
    switch (status) {
      case 'done': return <CheckCircle2 size={16} className="text-green-500" />
      case 'running': return (
        <motion.div className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full"
          animate={{ rotate: 360 }}
          transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
        />
      )
      case 'error': return <AlertCircle size={16} className="text-red-400" />
      default: return <Clock size={16} className="text-slate-300" />
    }
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="max-w-5xl mx-auto">
      <StepIndicator />

      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[26px] font-bold text-slate-800 mb-1">Information Extraction</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          Our AI pipeline parses each resume and job description to extract structured candidate data
          ready for scoring and normalization.
        </p>
      </motion.div>

      {/* Stats */}
      <motion.div variants={fadeUp} className="grid grid-cols-3 gap-4 mb-5">
        {[
          { label: 'Resumes Queued', value: totalResumes, color: 'text-sky-600', bg: 'bg-sky-50' },
          { label: 'Fields Extracted', value: fields.filter((f) => f.status === 'done').length, color: 'text-green-600', bg: 'bg-green-50' },
          { label: 'Confidence', value: isDone ? '96%' : '—', color: 'text-sky-600', bg: 'bg-sky-50' },
        ].map((stat) => (
          <div key={stat.label} className={`card p-4 ${stat.bg} border-transparent`}>
            <motion.p
              key={stat.value}
              className={`text-[28px] font-bold ${stat.color}`}
              initial={{ scale: 0.8 }}
              animate={{ scale: 1 }}
            >
              {stat.value}
            </motion.p>
            <p className="text-[12px] text-slate-500 font-medium">{stat.label}</p>
          </div>
        ))}
      </motion.div>

      {/* Extraction Fields */}
      <motion.div variants={fadeUp} className="card p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <FileSearch size={16} className="text-sky-500" />
            <h2 className="text-[14px] font-semibold text-slate-700">Extraction Fields</h2>
          </div>
          {!isRunning && !isDone && (
            <motion.button
              className="btn-primary py-2 px-4 text-[12px]"
              onClick={runExtraction}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
            >
              <FileSearch size={13} />
              Run Extraction
            </motion.button>
          )}
        </div>

        <div className="space-y-2.5">
          <AnimatePresence>
            {fields.map((field, idx) => {
              const Icon = field.icon
              return (
                <motion.div
                  key={field.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.06 }}
                  className={`flex items-center gap-3 p-3.5 rounded-xl border transition-all ${
                    field.status === 'done'
                      ? 'border-green-100 bg-green-50'
                      : field.status === 'running'
                      ? 'border-sky-200 bg-sky-50'
                      : 'border-slate-100 bg-slate-50'
                  }`}
                >
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    field.status === 'done' ? 'bg-green-100' : field.status === 'running' ? 'bg-sky-100' : 'bg-slate-100'
                  }`}>
                    <Icon size={15} className={
                      field.status === 'done' ? 'text-green-600' : field.status === 'running' ? 'text-sky-600' : 'text-slate-400'
                    } />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-semibold text-slate-700">{field.label}</p>
                    {field.result && (
                      <motion.p
                        className="text-[11px] text-slate-400 truncate"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                      >
                        {field.result}
                      </motion.p>
                    )}
                  </div>
                  <div className="flex-shrink-0">{statusIcon(field.status)}</div>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* CTA */}
      <motion.div variants={fadeUp} className="flex justify-end">
        <motion.button
          className="btn-primary px-6"
          onClick={handleContinue}
          disabled={!isDone}
          whileHover={isDone ? { scale: 1.02 } : undefined}
          whileTap={isDone ? { scale: 0.98 } : undefined}
        >
          Continue to Normalization
          <ArrowRight size={15} />
        </motion.button>
      </motion.div>
    </motion.div>
  )
}
