import { useCallback, useState, useRef, ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, X, FileText, CheckCircle2 } from 'lucide-react'
import { UploadedFile } from '@/types'

interface UploadCardProps {
  title: string
  subtitle: string
  accept?: string
  multiple?: boolean
  icon?: ReactNode
  color?: 'blue' | 'red'
  files: UploadedFile[]
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
  icon,
  color = 'blue',
  files,
  onUpload,
  onSelectFiles,
  onRemove,
  disabled = false,
}: UploadCardProps) {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

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
          className={btnClass}
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          whileHover={disabled ? undefined : { scale: 1.03 }}
          whileTap={disabled ? undefined : { scale: 0.97 }}
        >
          <Upload size={14} />
          {multiple ? 'Choose Folder' : 'Choose File'}
        </motion.button>
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
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          processFiles(e.target.files)
          e.target.value = ''
        }}
      />

      {/* Uploaded files list */}
      <AnimatePresence>
        {hasFiles && (
          <motion.div
            className="mt-4 space-y-2"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <div className="border-t border-slate-100 pt-3">
              {files.map((file) => (
                <motion.div
                  key={file.id}
                  className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-50 border border-slate-100 mb-1.5 group"
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 8 }}
                  layout
                >
                  <CheckCircle2
                    size={14}
                    className={`flex-shrink-0 ${
                      file.status === 'error'
                        ? 'text-red-400'
                        : file.status === 'uploading' || file.status === 'processing'
                          ? 'text-slate-300'
                          : 'text-sky-500'
                    }`}
                  />
                  <FileText size={13} className="text-slate-400 flex-shrink-0" />
                  <span className="text-[12px] text-slate-600 truncate flex-1 font-medium">
                    {file.name}
                  </span>
                  <span
                    className={`text-[11px] flex-shrink-0 max-w-[140px] truncate ${
                      file.status === 'error' ? 'text-red-400' : 'text-slate-400'
                    }`}
                    title={file.errorMessage || file.statusLabel}
                  >
                    {file.status === 'uploading' || file.status === 'processing'
                      ? file.statusLabel ||
                        (file.status === 'processing' ? 'Processing…' : 'Uploading…')
                      : file.status === 'error'
                        ? file.errorMessage || 'Failed'
                        : formatSize(file.size)}
                  </span>
                  <button
                    onClick={() => onRemove(file.id)}
                    disabled={disabled || file.status === 'uploading' || file.status === 'processing'}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-300 hover:text-red-400 ml-1 disabled:opacity-30"
                  >
                    <X size={13} />
                  </button>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
