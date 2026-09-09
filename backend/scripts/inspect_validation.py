import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("real_resumes_skills_validation.json", encoding="utf-8") as f:
    data = json.load(f)

for i, r in enumerate(data, 1):
    cname = r.get("candidate_name") or r.get("filename")
    fname = r.get("filename")
    print(f"\n================================================================================")
    print(f"RESUME #{i}: {cname} [{fname}]")
    print(f"================================================================================")
    for s in r["skills"]:
        v = s["verdict"]
        pts = s["coverage_points"]
        name = s["required_skill"]
        ev = s["candidate_evidence"]
        meth = s.get("method") or "none"
        if len(ev) > 90:
            ev = ev[:87] + "..."
        print(f"  {name:<40} | {v:<17} | {pts:4.2f} pts | {meth:<18} | {ev}")
