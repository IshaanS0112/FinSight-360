#!/usr/bin/env bash
# One-shot: create the GitHub repo and push FinSight 360.
# Prereq (once): install GitHub CLI and run `gh auth login`.
# Then, from inside the FinSight360/ folder:  ./PUSH_TO_GITHUB.sh
set -euo pipefail

REPO_NAME="finsight-360"

# Fail early rather than pushing a broken repo.
echo "Running the backend test suite first..."
(cd backend && python3 -m pytest -q)

git init -b main
git add .
git commit -m "FinSight 360: ratio engine, Altman Z/Z'/Z'' with sector-correct model selection, weighted health score, LLM narration over frozen structured context"

# --public (change to --private to keep it private). Creates the repo under your
# account, adds it as origin, and pushes main.
gh repo create "$REPO_NAME" --public --source=. --remote=origin --push \
  --description "Corporate financial health and risk intelligence: ratio engine, Altman Z/Z'/Z'' bankruptcy models applied to the population each was estimated on, weighted health scoring (FastAPI, PostgreSQL, React, Docker, Claude)"

echo "Done -> https://github.com/$(gh api user -q .login)/$REPO_NAME"

# --- No gh CLI? Create an empty repo named finsight-360 on github.com, then:
#   git init -b main && git add . && git commit -m "FinSight 360"
#   git remote add origin https://github.com/<you>/finsight-360.git
#   git push -u origin main
