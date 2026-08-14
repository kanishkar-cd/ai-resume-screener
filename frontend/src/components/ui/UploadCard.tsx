import { useCallback, useState, useRef, ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, X, FileText, CheckCircle2, Loader2 } from 'lucide-react'
import { UploadedFile, ResumeProcessingState } from '@/types'

interface UploadCardProps {
  title: string
  subtitle: string
  accept?: string
  multiple?: boolean
  directory?: boolean
  icon?: ReactNode
  color?: 'blue' | 'red'
  files: UploadedFile[]
  /** Optional per-resume processing map for inline progress tracking */
  resumeProcessing?: Record<string, ResumeProcessingState>
  /** Local/fake upload path (used by resume flow). Ignored when onSelectFiles is set. */
  onUpload?: (files: UploadedFile[]) => void
  /** Raw File selection — parent owns API upload (JD flow). */
  onSelectFiles?: (files: File[]) => void
  onRemove: (id: string) => void
  disabled?: boolean
}

function makeUploadedFile(file: File): UploadedFile {
  const ext = file.name.split('.').pop()?.toLowerCase()
  const typeMap: Record<string, UploadedFile['type']> = {
    pdf: 'pdf',
    docx: 'docx',
    doc: 'docx',
    txt: 'txt',
  }
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    size: file.size,
    type: typeMap[ext ?? ''] ?? 'unknown',
    status: 'done',
    uploadedAt: new Date(),
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function UploadCard({
  title,
  subtitle,
  accept = '.pdf,.docx,.doc,.txt',
  multiple = false,
  directory = false,
  icon,
  color = 'blue',
  files,
  resumeProcessing,
  onUpload,
  onSelectFiles,
  onRemove,
  disabled = false,
}: UploadCardProps) {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const filesInputRef = useRef<HTMLInputElement>(null)

  const isSky = color === 'blue'
  const accentBg = isSky ? 'bg-sky-50' : 'bg-red-50'
  const accentIcon = isSky ? 'text-sky-500' : 'text-red-400'
  const accentBorder = isSky ? 'border-sky-200' : 'border-red-100'
  const btnClass = isSky ? 'btn-primary' : 'btn-danger-outline'

  const processFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList || disabled) return
      const selected = Array.from(fileList)
      if (selected.length === 0) return
      if (onSelectFiles) {
        onSelectFiles(selected)
        return
      }
      onUpload?.(selected.map(makeUploadedFile))
    },
    [disabled, onSelectFiles, onUpload]
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      processFiles(e.dataTransfer.files)
    },
    [processFiles]
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    if (!disabled) setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const openFilePicker = () => {
    inputRef.current?.click()
  }

  const hasFiles = files.length > 0

  return (
    <motion.div
      className={`upload-dropzone p-6 ${isDragging ? 'drag-over' : ''}`}
      style={{ background: isDragging ? (isSky ? '#f0f9ff' : '#fff5f5') : '#ffffff' }}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      {/* Icon */}
      <motion.div
        className={`w-16 h-16 rounded-2xl ${accentBg} flex items-center justify-center mx-auto mb-4 ${accentBorder} border`}
        animate={isDragging ? { scale: 1.12, rotate: 2 } : { scale: 1, rotate: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      >
        <span className={accentIcon}>
          {icon || <Upload size={28} />}
        </span>
      </motion.div>

      <h3 className="text-[16px] font-bold text-slate-800 text-center mb-1">{title}</h3>
      <p className="text-[12px] text-slate-400 text-center mb-5">{subtitle}</p>

      {/* Upload Button */}
      <div className="flex justify-center mb-2">
        <motion.button
          type="button"
          className={btnClass}
          onClick={openFilePicker}
          disabled={disabled}
          whileHover={disabled ? undefined : { scale: 1.03 }}
          whileTap={disabled ? undefined : { scale: 0.97 }}
        >
          <Upload size={14} />
          {multiple ? 'Choose Folder' : 'Choose File'}
        </motion.button>
        {directory && (
          <motion.button
            type="button"
            className={`${btnClass} ml-2`}
            onClick={() => filesInputRef.current?.click()}
            disabled={disabled}
            whileHover={disabled ? undefined : { scale: 1.03 }}
            whileTap={disabled ? undefined : { scale: 0.97 }}
          >
            <Upload size={14} />
            Choose Files
          </motion.button>
        )}
      </div>

      <p className="text-[11px] text-slate-400 text-center mb-4">
        or drag and drop here
      </p>

      {/* Accepted formats */}
      <p className="text-[11px] text-slate-300 text-center">
        Accepted: PDF, DOCX, TXT (Max 10 MB{multiple ? ' each' : ''})
      </p>

      {/* Hidden file input */}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        {...(directory ? { webkitdirectory: '', directory: '' } : {})}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => {
          processFiles(e.target.files)
          e.target.value = ''
        }}
      />
      {directory && (
        <input
          ref={filesInputRef}
          type="file"
          accept={accept}
          multiple
          className="sr-only"
          disabled={disabled}
          onChange={(e) => {
            processFiles(e.target.files)
            e.target.value = ''
          }}
        />
      )}

      {/* Uploaded files list */}
      <AnimatePresence>
        {hasFiles && (
          <motion.div
            className="mt-4 space-y-2"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <div className="border-t border-slate-100 pt-3 space-y-2.5">
              {files.map((file) => {
                const proc = resumeProcessing?.[file.id]
                const isReady = proc?.normalized || (file.status === 'done' && !proc)
                const isFailed = file.status === 'error' || proc?.phase === 'failed'

                // Determine 3-step states
                let parsingState: 'pending' | 'in_progress' | 'completed' = 'pending'
                let extractionState: 'pending' | 'in_progress' | 'completed' = 'pending'
                let normalizationState: 'pending' | 'in_progress' | 'completed' = 'pending'

                if (proc) {
                  if (proc.phase === 'uploaded' || proc.phase === 'parsing' || file.status === 'uploading') {
                    parsingState = 'in_progress'
                  } else if (proc.phase === 'extracting') {
                    parsingState = 'completed'
                    extractionState = 'in_progress'
                  } else if (proc.phase === 'normalizing') {
                    parsingState = 'completed'
                    extractionState = 'completed'
                    normalizationState = 'in_progress'
                  } else if (proc.phase === 'normalized' || proc.normalized) {
                    parsingState = 'completed'
                    extractionState = 'completed'
                    normalizationState = 'completed'
                  }
                } else if (file.status === 'processing' || file.status === 'uploading') {
                  parsingState = 'in_progress'
                }

                return (
                  <motion.div
                    key={file.id}
                    className="p-3 rounded-xl bg-slate-50/80 border border-slate-200/80 group transition-all text-left"
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 8 }}
                    layout
                  >
                    {/* Top file row */}
                    <div className="flex items-center gap-2.5">
                      <FileText size={15} className="text-slate-400 shrink-0" />
                      <span className="text-[12px] text-slate-800 truncate flex-1 font-semibold">
                        {file.name}
                      </span>
                      {isReady && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200/80 shrink-0">
                          <CheckCircle2 size={12} className="text-emerald-600" />
                          Ready
                        </span>
                      )}
                      {isFailed && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-700 border border-red-200/80 shrink-0">
                          {file.errorMessage || proc?.errorMessage || 'Failed'}
                        </span>
                      )}
                      <span className="text-[11px] text-slate-400 font-mono shrink-0">
                        {formatSize(file.size)}
                      </span>
                      <button
                        type="button"
                        onClick={() => onRemove(file.id)}
                        disabled={disabled || file.status === 'uploading'}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-red-500 ml-1 p-1 rounded-md hover:bg-red-50 disabled:opacity-30 cursor-pointer shrink-0"
                        title="Remove file"
                      >
                        <X size={13} />
                      </button>
                    </div>

                    {/* Inline 3-Step processing status while in-progress */}
                    {!isReady && !isFailed && (
                      <div className="mt-2.5 pt-2.5 border-t border-slate-200/60 grid grid-cols-1 sm:grid-cols-3 gap-2">
                        {/* 1. Parsing */}
                        <div
                          className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[10px] font-bold border transition-colors ${
                            parsingState === 'completed'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200/70'
                              : parsingState === 'in_progress'
                                ? 'bg-blue-50 text-blue-700 border-blue-200/70 ring-1 ring-blue-400/20'
                                : 'bg-slate-100/70 text-slate-400 border-slate-200/60'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            {parsingState === 'completed' ? (
                              <CheckCircle2 size={12} className="text-emerald-600 shrink-0" />
                            ) : parsingState === 'in_progress' ? (
                              <Loader2 size={12} className="animate-spin text-blue-600 shrink-0" />
                            ) : null}
                            <span>Parsing</span>
                          </span>
                          <span className="text-[9px] uppercase tracking-wider font-semibold opacity-90">
                            {parsingState === 'completed' ? 'Completed' : parsingState === 'in_progress' ? 'In Progress' : 'Pending'}
                          </span>
                        </div>

                        {/* 2. Extraction */}
                        <div
                          className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[10px] font-bold border transition-colors ${
                            extractionState === 'completed'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200/70'
                              : extractionState === 'in_progress'
                                ? 'bg-blue-50 text-blue-700 border-blue-200/70 ring-1 ring-blue-400/20'
                                : 'bg-slate-100/70 text-slate-400 border-slate-200/60'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            {extractionState === 'completed' ? (
                              <CheckCircle2 size={12} className="text-emerald-600 shrink-0" />
                            ) : extractionState === 'in_progress' ? (
                              <Loader2 size={12} className="animate-spin text-blue-600 shrink-0" />
                            ) : null}
                            <span>Extraction</span>
                          </span>
                          <span className="text-[9px] uppercase tracking-wider font-semibold opacity-90">
                            {extractionState === 'completed' ? 'Completed' : extractionState === 'in_progress' ? 'In Progress' : 'Pending'}
                          </span>
                        </div>

                        {/* 3. Normalization */}
                        <div
                          className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[10px] font-bold border transition-colors ${
                            normalizationState === 'completed'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200/70'
                              : normalizationState === 'in_progress'
                                ? 'bg-blue-50 text-blue-700 border-blue-200/70 ring-1 ring-blue-400/20'
                                : 'bg-slate-100/70 text-slate-400 border-slate-200/60'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            {normalizationState === 'completed' ? (
                              <CheckCircle2 size={12} className="text-emerald-600 shrink-0" />
                            ) : normalizationState === 'in_progress' ? (
                              <Loader2 size={12} className="animate-spin text-blue-600 shrink-0" />
                            ) : null}
                            <span>Normalization</span>
                          </span>
                          <span className="text-[9px] uppercase tracking-wider font-semibold opacity-90">
                            {normalizationState === 'completed' ? 'Completed' : normalizationState === 'in_progress' ? 'In Progress' : 'Pending'}
                          </span>
                        </div>
                      </div>
                    )}
                  </motion.div>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
