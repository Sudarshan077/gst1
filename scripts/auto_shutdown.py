#!/usr/bin/env python3
"""Watch build state; when all tasks done, push to GitHub then shut down."""
import json, time, subprocess, os, sys

STATE = "D:/gst_filing_app/build/state.json"
ROOT = "D:/gst_filing_app"

def all_done():
    s = json.load(open(STATE, encoding="utf-8"))
    if s.get("status") == "escalated":
        print("BUILD ESCALATED — not shutting down, needs human attention")
        return False
    if s.get("status") == "complete":
        return True
    tasks = s.get("tasks", {})
    return all(t.get("status") == "done" for t in tasks.values()) and len(tasks) > 0

def push_to_github():
    print("Pushing to GitHub...")
    subprocess.run(["python", "scripts/generate_tracker.py"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "add", "README.md", "docs/BUILD_TRACKER.md"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "commit", "-m", "TASK final: regenerate tracker before shutdown"], cwd=ROOT, capture_output=True)
    r = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    print("push result:", r.returncode, (r.stdout or r.stderr)[:200])
    return r.returncode == 0

print("Auto-shutdown watcher started — polling every 120s")
print("Cancel shutdown with: shutdown /a")
for i in range(999):
    try:
        if all_done():
            print("ALL TASKS DONE — pushing to GitHub, then shutting down in 60s")
            push_to_github()
            subprocess.run(["shutdown", "/s", "/t", "60", "/c",
                "GST build complete — auto shutdown. Cancel: shutdown /a"])
            print("Shutdown scheduled (60s grace). Cancel with: shutdown /a")
            break
        else:
            s = json.load(open(STATE, encoding="utf-8"))
            done = sum(1 for t in s.get("tasks",{}).values() if t.get("status")=="done")
            total = len(s.get("tasks",{}))
            print(f"[check {i+1}] {done}/{total} done, status={s.get('status')}")
    except Exception as e:
        print(f"[check {i+1}] error: {e}")
    time.sleep(120)
print("Watcher finished")
