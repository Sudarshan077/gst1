#!/usr/bin/env python3
"""Single-shot check: if all GST build tasks done, push + shutdown. Exits immediately."""
import json, subprocess, os

STATE = "D:/gst_filing_app/build/state.json"
ROOT = "D:/gst_filing_app"
LOG = "D:/gst_filing_app/build/auto_shutdown.log"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

s = json.load(open(STATE, encoding="utf-8"))
done = sum(1 for t in s.get("tasks",{}).values() if t.get("status")=="done")
total = len(s.get("tasks",{}))
status = s.get("status")

if status == "escalated":
    log(f"[check] BUILD ESCALATED at {done}/{total} — NOT shutting down, needs human")
elif all(t.get("status") == "done" for t in s.get("tasks",{}).values()) and total > 0:
    log(f"[check] ALL {total} TASKS DONE — pushing to GitHub, then shutting down in 60s")
    subprocess.run(["python", "scripts/generate_tracker.py"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "add", "README.md", "docs/BUILD_TRACKER.md"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "commit", "-m", "TASK final: regenerate tracker before shutdown"], cwd=ROOT, capture_output=True)
    r = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    log(f"[check] push result: {r.returncode} {(r.stdout or r.stderr)[:200]}")
    subprocess.run(["shutdown", "/s", "/t", "60", "/c",
        "GST build complete — auto shutdown. Cancel: shutdown /a"])
    log("[check] Shutdown scheduled (60s grace). Cancel with: shutdown /a")
else:
    log(f"[check] {done}/{total} done, status={status}, current={s.get('current_task')}")
