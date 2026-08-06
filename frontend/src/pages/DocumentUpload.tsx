import { motion } from 'framer-motion'
import {
  FileText,
  Shield,
  Lightbulb,
  Check,
  ArrowRight,
  FileCheck,
} from 'lucide-react'
import UploadCard from '@/components/ui/UploadCard'
import { usePipeline } from '@/store/pipelineStore'
import { UploadedFile } from '@/types'
import { useNavigate } from 'react-router-dom'

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
}

const container = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.08 },
  },
}

export default function DocumentUpload() {
  const { state, dispatch, canProceedJD, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()

  const handleJDUpload = (files: UploadedFile[]) => {
    if (files[0]) dispatch({ type: 'SET_JD', payload: files[0] })
  }

  const handleRemoveJD = () => dispatch({ type: 'SET_JD', payload: null })

  const handleContinue = () => {
    if (!canProceedJD) return
    completeAndAdvance()
    navigate('/weightage')
  }

  const jdCount = state.upload.jobDescription ? 1 : 0

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="max-w-5xl mx-auto"
    >
      {/* Page Header */}
      <motion.div variants={fadeUp} className="mb-5">
        <h1 className="text-[26px] font-bold text-slate-800 mb-1">Document Upload</h1>
        <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
          Upload the <strong className="text-slate-600">job description (JD) document</strong>.
          The file is verified for format, size, and readability before defining scoring criteria weights.
        </p>
      </motion.div>

      {/* Info Strip */}
      <motion.div
        variants={fadeUp}
        className="card glow-border-sky mb-5 p-0 overflow-hidden"
      >
        <div className="flex divide-x divide-slate-100">
          {/* Supported Formats */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              Supported Formats
            </p>
            <div className="flex items-center gap-3">
              {[
                { icon: '📄', label: 'PDF', color: 'text-red-500' },
                { icon: '📝', label: 'DOCX', color: 'text-sky-500' },
                { icon: '📃', label: 'TXT', color: 'text-slate-400' },
              ].map((fmt) => (
                <motion.div
                  key={fmt.label}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-100"
                  whileHover={{ scale: 1.04 }}
                >
                  <span className="text-[13px]">{fmt.icon}</span>
                  <span className={`text-[12px] font-bold ${fmt.color}`}>{fmt.label}</span>
                </motion.div>
              ))}
            </div>
          </div>

          {/* File Limit */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              File Limit
            </p>
            <div className="flex items-center gap-2">
              <FileCheck size={16} className="text-sky-400" />
              <span className="text-[13px] font-semibold text-slate-700">
                Max 10 MB per file
              </span>
            </div>
          </div>

          {/* Security */}
          <div className="flex-1 p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              Security
            </p>
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-sky-400" />
              <span className="text-[13px] font-semibold text-slate-700">
                Files are encrypted and secure
              </span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Upload Card (Job Description Only) */}
      <motion.div variants={fadeUp} className="mb-5">
        <UploadCard
          title="Job Description"
          subtitle="Upload the job description (JD) file"
          icon={<FileText size={28} />}
          color="blue"
          multiple={false}
          files={state.upload.jobDescription ? [state.upload.jobDescription] : []}
          onUpload={handleJDUpload}
          onRemove={handleRemoveJD}
        />
      </motion.div>

      {/* Bottom Row */}
      <motion.div variants={fadeUp} className="card glow-border-sky p-0 overflow-hidden">
        <div className="flex divide-x divide-slate-100">
          {/* Total Files */}
          <div className="p-5 min-w-[160px]">
            <div className="flex items-center gap-2 mb-2">
              <FileText size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                JD Uploaded
              </p>
            </div>
            <motion.p
              key={jdCount}
              className="text-[32px] font-bold text-slate-800 leading-none"
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 300 }}
            >
              {jdCount}
            </motion.p>
            <p className="text-[11px] text-slate-400 mt-1">
              {jdCount === 0 ? 'No JD uploaded yet' : 'Job Description ready'}
            </p>
          </div>

          {/* Tips */}
          <div className="flex-1 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Lightbulb size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                Upload Tips
              </p>
            </div>
            <ul className="space-y-1.5">
              {[
                'Ensure the JD file is clear and readable.',
                'Include key role requirements, qualifications, and responsibilities.',
                'Supported languages: English only.',
              ].map((tip, i) => (
                <motion.li
                  key={i}
                  className="flex items-start gap-2 text-[12px] text-slate-500"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.4 + i * 0.07 }}
                >
                  <Check size={13} className="text-sky-400 flex-shrink-0 mt-0.5" />
                  {tip}
                </motion.li>
              ))}
            </ul>
          </div>

          {/* CTA */}
          <div className="flex flex-col items-center justify-center p-6 min-w-[220px]">
            <motion.button
              className="btn-primary w-full justify-center text-[13px] py-3 mb-2"
              onClick={handleContinue}
              disabled={!canProceedJD}
              whileHover={canProceedJD ? { scale: 1.02 } : undefined}
              whileTap={canProceedJD ? { scale: 0.98 } : undefined}
              animate={canProceedJD ? { boxShadow: ['0 4px 12px rgba(2,132,199,0.3)', '0 6px 20px rgba(2,132,199,0.5)', '0 4px 12px rgba(2,132,199,0.3)'] } : undefined}
              transition={canProceedJD ? { duration: 2, repeat: Infinity } : undefined}
            >
              Continue to Stage 2
              <ArrowRight size={15} />
            </motion.button>
            <p className="text-[10px] text-slate-400 text-center leading-relaxed">
              You can only proceed when<br />Job Description is uploaded.
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}
