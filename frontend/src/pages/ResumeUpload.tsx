import { motion } from 'framer-motion'
import {
  Folder,
  Shield,
  Lightbulb,
  Check,
  ArrowLeft,
  ArrowRight,
  FileCheck,
  Users,
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

export default function ResumeUpload() {
  const { state, dispatch, canProceedResumes, completeAndAdvance } = usePipeline()
  const navigate = useNavigate()

  const handleResumeUpload = (files: UploadedFile[]) => {
    dispatch({ type: 'ADD_RESUMES', payload: files })
  }

  const handleRemoveResume = (id: string) =>
    dispatch({ type: 'REMOVE_RESUME', payload: id })

  const handleContinue = () => {
    if (!canProceedResumes) return
    completeAndAdvance()
    navigate('/ranking')
  }

  const handleBack = () => {
    navigate('/weightage')
  }

  const resumeCount = state.upload.resumes.length

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="max-w-5xl mx-auto"
    >
      {/* Page Header */}
      <motion.div variants={fadeUp} className="mb-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold text-slate-800 mb-1">Resume Upload</h1>
          <p className="text-[13px] text-slate-500 max-w-xl leading-relaxed">
            Upload candidate <strong className="text-slate-600">resumes or resume folders</strong>.
            All documents are automatically extracted, standardized, and scored against your weighted criteria.
          </p>
        </div>
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
                Max 10 MB per resume
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

      {/* Upload Card (Resume Folder Only) */}
      <motion.div variants={fadeUp} className="mb-5">
        <UploadCard
          title="Resume Folder"
          subtitle="Upload candidate resumes or a folder of resumes"
          icon={<Folder size={28} />}
          color="red"
          multiple={true}
          files={state.upload.resumes}
          onUpload={handleResumeUpload}
          onRemove={handleRemoveResume}
        />
      </motion.div>

      {/* Bottom Summary Strip & Action Footer */}
      <motion.div variants={fadeUp} className="card glow-border-sky p-0 overflow-hidden mb-5">
        <div className="flex divide-x divide-slate-100">
          {/* Total Resumes */}
          <div className="p-5 min-w-[180px]">
            <div className="flex items-center gap-2 mb-2">
              <Users size={14} className="text-sky-400" />
              <p className="text-[10px] font-bold text-sky-600 uppercase tracking-widest">
                Resumes Queued
              </p>
            </div>
            <motion.p
              key={resumeCount}
              className="text-[32px] font-bold text-slate-800 leading-none"
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 300 }}
            >
              {resumeCount}
            </motion.p>
            <p className="text-[11px] text-slate-400 mt-1">
              {resumeCount === 0 ? 'No resumes uploaded yet' : `${resumeCount} candidate resume${resumeCount > 1 ? 's' : ''} ready`}
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
                'Ensure candidate resumes are clearly formatted and text-searchable.',
                'Multiple files or whole folders can be selected at once.',
                'System automatically removes duplicates and standardizes fields.',
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
        </div>
      </motion.div>

      {/* Action Footer Bar */}
      <motion.div variants={fadeUp} className="card p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
            PIPELINE PROGRESS
          </p>
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-sky-600" />
            <div className="w-6 h-2 rounded-full bg-slate-200" />
            <div className="w-6 h-2 rounded-full bg-slate-200" />
          </div>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <motion.button
            onClick={handleBack}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="btn-outline flex-1 sm:flex-initial py-2.5 px-5 text-[13px] flex items-center justify-center gap-2 font-medium"
          >
            <ArrowLeft size={15} />
            Back to Weightage
          </motion.button>

          <motion.button
            onClick={handleContinue}
            disabled={!canProceedResumes}
            whileHover={canProceedResumes ? { scale: 1.02 } : undefined}
            whileTap={canProceedResumes ? { scale: 0.98 } : undefined}
            className={`flex-1 sm:flex-initial py-2.5 px-6 rounded-xl text-[13px] font-semibold flex items-center justify-center gap-2 transition-all shadow-sky-sm ${
              canProceedResumes
                ? 'bg-sky-600 hover:bg-sky-700 text-white cursor-pointer'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed border-transparent shadow-none'
            }`}
          >
            Continue to Candidate Ranking
            <ArrowRight size={15} />
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}
