#!/usr/bin/env python3
"""Watch build state; when all tasks done, push to GitHub then shut down.
Resilient version — survives session cleanup via persist_on_release."""
import json, time, subprocess, os

STATE = "D:/gst_filing_app/build/state.json"
ROOT = "D:/gst_filing_app"

def all_done():
    s = json.load(open(STATE, encoding="utf-8"))
    if s.get("status") == "escalated":
        return False  # needs human attention
    tasks = s.get("tasks", {})
    if not tasks:
        return False
    return all(t.get("status") == "done" for t in tasks.values())

def push_to_github():
    subprocess.run(["python", "scripts/generate_tracker.py"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "add", "README.md", "docs/BUILD_TRACKER.md"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "commit", "-m", "TASK final: regenerate tracker before shutdown"], cwd=ROOT, capture_output=True)
    r = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    return r.returncode == 0

while True:
    try:
        s = json.load(open(STATE, encoding="utf-8"))
        done = sum(1 for t in s.get("tasks",{}).values() if t.get("status")=="done")
        total = len(s.get("tasks",{}))
        if all_done():
            print(f"ALL {total} TASKS DONE — pushing to GitHub, then shutting down in 60s")
            push_to_github()
            subprocess.run(["shutdown", "/s", "/t", "60", "/c",
                "GST build complete — auto shutdown. Cancel: shutdown /a"])
            break
        elif s.get("status") == "escalated":
            print(f"BUILD ESCALATED at {done}/{total} — NOT shutting down")
            break
        else:
            print(f"[poll] {done}/{total} done, status={s.get('status')}, current={s.get('current_task')}")
    except Exception as e:
        print(f"[poll] error: {e}")
    time.sleep(120)
