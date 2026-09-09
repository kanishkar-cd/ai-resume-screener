import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("real_resumes_skills_validation.json", encoding="utf-8") as f:
    data = json.load(f)

for i in range(4):
    r = data[i]
    cname = r.get("candidate_name") or r.get("filename")
    fname = r.get("filename")
    print(f"\n================================================================================")
    print(f"RESUME #{i+1}: {cname} [{fname}]")
    print(f"================================================================================")
    for s in r["skills"]:
        v = s["verdict"]
        pts = s["coverage_points"]
        name = s["required_skill"]
        ev = s["candidate_evidence"]
        meth = s.get("method") or "none"
        if len(ev) > 80:
            ev = ev[:77] + "..."
        flag = "[MATCH]" if v == "MATCHED" else ("[PART ]" if v == "PARTIALLY_MATCHED" else "[NO_M ]")
        print(f"  {flag} {name:<38} | {v:<17} | {pts:4.2f} pts | {meth:<18} | {ev}")
