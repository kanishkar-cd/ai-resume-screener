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
  onUpload: (files: UploadedFile[]) => void
  onRemove: (id: string) => void
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
  onRemove,
}: UploadCardProps) {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const isSky = color === 'blue'
  const accentBg = isSky ? 'bg-sky-50' : 'bg-red-50'
  const accentIcon = isSky ? 'text-sky-500' : 'text-red-400'
  const accentBorder = isSky ? 'border-sky-200' : 'border-red-100'
  const btnClass = isSky ? 'btn-primary' : 'btn-danger-outline'

  const processFiles = (fileList: FileList | null) => {
    if (!fileList) return
    const uploads = Array.from(fileList).map(makeUploadedFile)
    onUpload(uploads)
  }

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      processFiles(e.dataTransfer.files)
    },
    [onUpload]
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
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
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
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
        onChange={(e) => processFiles(e.target.files)}
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
                  <CheckCircle2 size={14} className="text-sky-500 flex-shrink-0" />
                  <FileText size={13} className="text-slate-400 flex-shrink-0" />
                  <span className="text-[12px] text-slate-600 truncate flex-1 font-medium">
                    {file.name}
                  </span>
                  <span className="text-[11px] text-slate-400 flex-shrink-0">
                    {formatSize(file.size)}
                  </span>
                  <button
                    onClick={() => onRemove(file.id)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-300 hover:text-red-400 ml-1"
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
