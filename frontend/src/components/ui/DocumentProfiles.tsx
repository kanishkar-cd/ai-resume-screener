import type { Document as ApiDocument, ExtractedJobDescription, ExtractedResume, NormalizedJobDescription, NormalizedResume, ParsedDocument } from '@/api'

type ProfileProvider = 'affinda' | 'local' | 'unknown'

function profileProvider(document?: ApiDocument | null, extracted?: ExtractedResume | null): ProfileProvider {
  const provider = document?.metadata_json?.document_intelligence_provider
  if (provider === 'affinda' || provider === 'local') return provider
  return extracted?.raw_metadata?.provider === 'affinda' ? 'affinda' : 'unknown'
}

function ProviderStatus({ document, extracted }: { document?: ApiDocument | null; extracted?: ExtractedResume | null }) {
  const provider = profileProvider(document, extracted)
  if (provider === 'unknown') return null
  const fallbackUsed = provider === 'local'
  return <div className="flex flex-wrap items-center gap-2">
    <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${fallbackUsed ? 'bg-slate-100 text-slate-700' : 'bg-indigo-50 text-indigo-700'}`}>
      {fallbackUsed ? 'Local Parser' : 'Affinda'}
    </span>
    {fallbackUsed && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-700">Fallback used</span>}
  </div>
}

function ProcessingTrace({ fallbackUsed }: { fallbackUsed: boolean }) {
  return <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-[11px] font-semibold text-slate-600">
      <span>Parsing <span className="text-emerald-600">Completed</span></span>
      <span>Extraction <span className="text-emerald-600">Completed</span></span>
      <span>Normalization <span className="text-emerald-600">Completed</span></span>
    </div>
    {fallbackUsed && <p className="mt-2 text-[11px] text-amber-700">Affinda was unavailable for this document, so processing completed with the local parser.</p>}
  </div>
}

const values = (items?: Array<string | null | undefined>) => (items ?? []).filter((item): item is string => Boolean(item))

function Chips({ items }: { items?: Array<string | null | undefined> }) {
  const filtered = values(items)
  if (!filtered.length) return <p className="text-[12px] text-slate-400">Not provided by the backend</p>
  return <div className="flex flex-wrap gap-2">{filtered.map((item) => <span key={item} className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-700">{item}</span>)}</div>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p>{children}</div>
}

function experiencePresentation(normalized: NormalizedJobDescription, parsed?: ParsedDocument | null) {
  const unique = new Map<string, string>()
  normalized.experience_requirements.forEach((item) => {
    const key = `${item.minimum_months ?? ''}:${item.maximum_months ?? ''}`
    const current = unique.get(key)
    if (!current || item.display_value.length < current.length) unique.set(key, item.display_value)
  })
  const sourceLine = parsed?.raw_text.split(/\r?\n/).map((line) => line.trim()).find((line) => /professional\s+or\s+internship\s+experience/i.test(line))
  const description = sourceLine
    ?.replace(/^\s*(?:experience\s*:\s*)?\d+\s*(?:[-–—]|to)\s*\d+\s*years?\s*(?:of\s+)?/i, '')
    .trim()
  return { ranges: [...unique.values()], description: description ? `${description.charAt(0).toUpperCase()}${description.slice(1)}` : null }
}

export function JobProfile({ normalized, extracted, parsed, document }: { normalized: NormalizedJobDescription; extracted?: ExtractedJobDescription | null; parsed?: ParsedDocument | null; document?: ApiDocument | null }) {
  const experience = experiencePresentation(normalized, parsed)
  const groupedSkills = new Set([...normalized.required_skills, ...normalized.preferred_skills].map((skill) => skill.trim().toLocaleLowerCase()))
  const additionalSkills = normalized.skills.filter((skill) => !groupedSkills.has(skill.trim().toLocaleLowerCase()))
  return <section className="card p-6 space-y-6">
    <div className="flex justify-end"><ProviderStatus document={document}/></div>
    <ProcessingTrace fallbackUsed={profileProvider(document) === 'local'}/>
    <div><p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600">Profile ready</p><h2 className="mt-1 text-[20px] font-bold text-slate-900">Final Job Profile</h2><p className="mt-1 text-[12px] text-slate-500">Structured profile · ruleset {normalized.ruleset_version}</p></div>
    <div className="grid gap-6 md:grid-cols-2">
      <Field label="Job title / role"><p className="text-[13px] font-semibold text-slate-800">{normalized.job_title || 'Not provided by the backend'}</p></Field>
      <Field label="Domain"><p className="text-[13px] font-semibold text-slate-800">{normalized.domain || 'Not provided by the backend'}</p></Field>
      <Field label="Experience requirements"><Chips items={experience.ranges} />{experience.description && <p className="mt-2 text-[12px] leading-relaxed text-slate-600">{experience.description}</p>}</Field>
      <Field label="Required skills"><Chips items={normalized.required_skills} /></Field>
      <Field label="Preferred skills"><Chips items={normalized.preferred_skills} /></Field>
      {additionalSkills.length > 0 && <Field label="Additional skills"><Chips items={additionalSkills} /></Field>}
      <Field label="Education / degree requirements"><Chips items={normalized.degree_requirements} /></Field>
      <Field label="Accepted disciplines"><Chips items={normalized.education_disciplines} /></Field>
      <Field label="Responsibilities">{normalized.responsibilities.length ? <ul className="space-y-2">{normalized.responsibilities.map((item) => <li key={item} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-[12px] leading-relaxed text-slate-700">{item}</li>)}</ul> : <p className="text-[12px] text-slate-400">Not provided by the backend</p>}</Field>
      <Field label="Certifications"><Chips items={normalized.certifications} /></Field>
      <Field label="Keywords"><Chips items={normalized.keywords} /></Field>
    </div>
    {extracted && <details className="border-t border-slate-100 pt-4"><summary className="cursor-pointer text-[12px] font-semibold text-slate-700">View extracted data</summary><div className="mt-4 grid gap-5 md:grid-cols-2"><Field label="Responsibilities"><Chips items={extracted.responsibilities}/></Field><Field label="Certifications"><Chips items={extracted.certifications}/></Field><Field label="Extracted education"><Chips items={extracted.education}/></Field><Field label="Extracted experience"><Chips items={extracted.experience}/></Field></div></details>}
    {parsed && <details className="border-t border-slate-100 pt-4"><summary className="cursor-pointer text-[12px] font-semibold text-slate-700">View raw JD</summary><pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-[11px] leading-relaxed text-slate-600">{parsed.raw_text}</pre></details>}
  </section>
}

export function CandidateProfile({ normalized, extracted, document }: { normalized: NormalizedResume; extracted?: ExtractedResume | null; document?: ApiDocument | null }) {
  const aiRecovery = extracted?.raw_metadata?.ai_recovery === 'merged'
  return <section className="card p-6 space-y-6">
    <div className="flex justify-end"><ProviderStatus document={document} extracted={extracted}/></div>
    <div className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600">Profile ready</p><h3 className="mt-1 text-[18px] font-bold text-slate-900">Final Candidate Profile</h3>{extracted?.candidate_name && <p className="mt-1 text-[13px] font-semibold text-slate-700">{extracted.candidate_name}</p>}<p className="mt-1 text-[12px] text-slate-500">Structured profile · ruleset {normalized.ruleset_version}</p></div>{aiRecovery && <span className="rounded-full bg-violet-50 px-2.5 py-1 text-[10px] font-semibold text-violet-700">AI-assisted recovery</span>}</div>
    <div className="grid gap-5 md:grid-cols-2">
      <Field label="Contact"><p className="text-[12px] text-slate-700">{normalized.email || 'Email not provided'}</p><p className="mt-1 text-[12px] text-slate-500">{normalized.phone || 'Phone not provided'}</p></Field>
      <Field label="Location"><Chips items={normalized.locations.map((item) => item.display_name)}/></Field>
      <Field label="Current / latest designation"><p className="text-[13px] font-semibold text-slate-800">{normalized.job_titles[0] || 'No designation listed'}</p></Field>
      <Field label="Skills"><Chips items={normalized.skills}/></Field>
      <Field label="Languages"><Chips items={normalized.languages}/></Field>
      <Field label="Certifications"><Chips items={normalized.certifications}/></Field>
    </div>
    <div><p className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">Education</p>{normalized.education.length ? <div className="space-y-2">{normalized.education.map((item, index) => <div key={`${item.institution}-${index}`} className="rounded-xl border border-slate-100 p-3 text-[12px] text-slate-600"><p className="font-semibold text-slate-800">{values([item.degree, item.field_of_study]).join(' · ') || 'Education'}</p><p className="mt-1">{values([item.institution, item.graduation_date]).join(' · ')}</p></div>)}</div> : <p className="text-[12px] text-slate-400">No formal education listed</p>}</div>
    <div><p className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">Work experience</p>{normalized.experience.length ? <div className="space-y-2">{normalized.experience.map((item, index) => <div key={`${item.company}-${index}`} className="rounded-xl border border-slate-100 p-3 text-[12px] text-slate-600"><p className="font-semibold text-slate-800">{values([item.job_title, item.company]).join(' · ') || 'Experience'}</p><p className="mt-1">{values([item.start_date, item.end_date, item.duration_display]).join(' · ')}</p></div>)}</div> : <p className="text-[12px] text-slate-400">No professional experience listed</p>}</div>
    {extracted && <details className="border-t border-slate-100 pt-4"><summary className="cursor-pointer text-[12px] font-semibold text-slate-700">View extracted data</summary><div className="mt-4 space-y-5">
      <div className="flex flex-wrap items-center gap-2"><ProviderStatus document={document} extracted={extracted}/>{aiRecovery && <span className="rounded-full bg-violet-50 px-2.5 py-1 text-[10px] font-semibold text-violet-700">AI-assisted recovery</span>}</div>
      <Field label="Extracted identity"><p className="text-[12px] text-slate-700">{extracted.candidate_name || 'Not provided'}{extracted.designation ? ` · ${extracted.designation}` : ''}</p></Field>
      <div><p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">Extracted work experience</p>{extracted.experience.length ? <div className="space-y-2">{extracted.experience.map((item, index) => <div key={`${item.company}-${index}`} className="rounded-xl bg-slate-50 p-3 text-[11px] text-slate-600"><p className="text-[12px] font-semibold text-slate-800">{values([item.title || item.designation, item.company]).join(' · ') || 'Experience'}</p><p className="mt-1">{values([item.start_date, item.end_date, item.duration]).join(' · ')}</p>{item.responsibilities?.length ? <ul className="mt-2 list-disc space-y-1 pl-4">{item.responsibilities.map((value) => <li key={value}>{value}</li>)}</ul> : null}</div>)}</div> : <p className="text-[12px] text-slate-400">No professional experience listed</p>}</div>
      <div><p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">Projects</p>{extracted.projects.length ? <div className="space-y-2">{extracted.projects.map((project, index) => <div key={`${project.name}-${index}`} className="rounded-xl bg-slate-50 p-3"><p className="text-[12px] font-semibold text-slate-800">{project.name || 'Technical Project'}</p>{project.description && <p className="mt-1 text-[11px] leading-relaxed text-slate-600">{project.description}</p>}<div className="mt-2"><Chips items={project.technologies}/></div></div>)}</div> : <p className="text-[12px] text-slate-400">No projects listed</p>}</div>
    </div></details>}
  </section>
}
