# Demo screenshots

Output of `scripts/app_tour.cjs` lands here:
- `NN-<screen>.png` — one full-page screenshot per verified screen
- `tour-report.json` — the `[STEP]` log (screen → evidence → screenshot path)

Regenerate with:
```bash
cd frontend
NODE_PATH="$PWD/node_modules" node ../scripts/app_tour.cjs
```
