# Capsule 🛡️

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-purple)](LICENSE)

**Capsule** is an AI-powered CI/CD companion that watches your pull requests, checks them against your Business Requirements, spots risky changes, and auto-publishes versioned changelogs. Think of it as having a senior engineer reviewing every PR, but faster and without the coffee breaks.

---

## Quick Overview

What does Capsule actually do?

1. **Watches GitHub PRs** → Gets notified when you open a PR
2. **Reads your Business Rules** → Loads your BRD document to understand what matters
3. **Analyzes code changes** → Uses AI to understand what changed and why
4. **Checks for violations** → Makes sure nothing breaks your critical workflows
5. **Generates summaries** → Creates a human-readable summary in your PR
6. **Auto-versions releases** → Bumps version numbers automatically (MAJOR, MINOR, PATCH)
7. **Pushes changelogs** → Commits versioned changelog entries to your release repo

**End result**: Your team spends less time writing release notes and more time shipping code.

---

## 📋 Quick Links

- [Setup Instructions](#-setup--step-by-step) - Get it running in 15 minutes
- [How Multi-Repo Works](#how-multi-repo-orchestration-works) - For teams managing multiple codebases
- [Architecture](#architecture) - The boring but important stuff
- [Troubleshooting](#troubleshooting) - When things go wrong

---

## Architecture

```mermaid
graph TD
    subgraph GitHub["📦 GitHub"]
        PR["You open a PR"]
    end
    
    subgraph Jenkins["🔧 Jenkins"]
        Webhook["Webhook Event"]
    end
    
    subgraph Capsule["🛡️ Capsule Backend"]
        BRD["Reads Business Rules<br/>from BRD Document"]
        Analyzer["AI Analyzer<br/>NVIDIA LLM"]
        Cache["Results Cache<br/>Redis"]
    end
    
    subgraph Output["📝 Output"]
        PRComment["PR Comment<br/>with Summary"]
        Changelog["Changelog Entry<br/>in Release Repo"]
    end
    
    PR -->|"GitHub Webhook"| Webhook
    Webhook -->|"POST /webhooks"| Capsule
    BRD -.->|"Ground Truth"| Analyzer
    Analyzer -->|"AI Analysis"| Cache
    Cache --> PRComment
    Cache --> Changelog
```

**Flow in human terms:**
> Your GitHub webhook triggers Jenkins → Jenkins tells Capsule → Capsule loads your business rules → AI analyzes the PR diff → Results are cached → Chrome extension shows summary → On merge, changelog auto-updates

---

## Key Features

### 🤖 AI-Powered Code Analysis
- Reads diffs and explains what changed in plain English
- Uses NVIDIA's Llama 3.1 70B model (enterprise-grade accuracy)
- Detects patterns your BRD cares about

### ✅ Business Rule Checking
- Compares code changes against your BRD
- Warns if a PR modifies critical workflows
- Prevents rule violations from shipping

### 🛡️ Anti-Hallucination Layer
- 8-layer validation system ensures AI doesn't make stuff up
- Physical file validation checks
- Low temperature inference (0.1) for consistency
- Confidence scoring on all findings

### 📦 Smart Versioning
- **MAJOR**: When workflow logic changes
- **MINOR**: When features are added
- **PATCH**: When bugs are fixed
- Automatic SemVer bumping on each merge

### 🎨 Floating Dashboard
- Chrome extension injects a side panel in GitHub
- No styling conflicts (Shadow DOM isolated)
- Shows summaries without page reload

### 🚀 Jenkins Integration
- Multibranch pipeline ready
- Analyzes PRs before merge
- Auto-publishes on merge to main

---

## Tech Stack (What's Under the Hood)

| What | Technology | Why |
|-----|-----------|-----|
| **API** | FastAPI | Fast, async, great for webhooks |
| **Database** | PostgreSQL + AsyncPG | Reliable, handles concurrent requests |
| **Cache** | Redis | Lightning-fast result caching |
| **Task Queue** | Celery | Handles long-running PR analysis in background |
| **AI Model** | NVIDIA NIM (Llama 3.1 70B) | Accurate code understanding |
| **Frontend** | Vanilla JS + Shadow DOM | Works everywhere, no dependencies |
| **CI/CD** | Jenkins + Multibranch Pipeline | Standard enterprise setup |
| **Container** | Docker Compose | Everything in one `docker-compose up` |
| **Reverse Proxy** | Nginx | Load balancing, SSL termination |

---

## How Multi-Repo Orchestration Works

Running multiple projects? Capsule can analyze PRs from all of them and consolidate everything into one changelog.

### The Setup

```
Your Organization
├── app-backend (monitored)
├── app-frontend (monitored)
├── app-shared (monitored)
└── releases (central changelog destination)
```

### What Happens

```mermaid
graph LR
    Repo1["📱 Frontend Repo<br/>PR #42 Opened"]
    Repo2["⚙️ Backend Repo<br/>PR #88 Opened"]
    Repo3["📚 Shared Repo<br/>PR #15 Opened"]
    
    Webhook1["Webhook Event"]
    Webhook2["Webhook Event"]
    Webhook3["Webhook Event"]
    
    Jenkins["Jenkins Pipeline<br/>Processes All PRs"]
    Capsule["Capsule Backend<br/>Analyzes Each PR<br/>Against Same BRD"]
    
    Cache["Analysis Cache<br/>Redis"]
    
    Release["Release Repo<br/>Single changelog.txt"]
    
    Repo1 -->|"PR opened/updated"| Webhook1
    Repo2 -->|"PR opened/updated"| Webhook2
    Repo3 -->|"PR opened/updated"| Webhook3
    
    Webhook1 --> Jenkins
    Webhook2 --> Jenkins
    Webhook3 --> Jenkins
    
    Jenkins -->|"Analyze PR #42"| Capsule
    Jenkins -->|"Analyze PR #88"| Capsule
    Jenkins -->|"Analyze PR #15"| Capsule
    
    Capsule -->|"Store results"| Cache
    
    Cache -->|"On merge to main"| Release
    
    style Repo1 fill:#e1f5ff
    style Repo2 fill:#e1f5ff
    style Repo3 fill:#e1f5ff
    style Release fill:#c8e6c9
```

### Real Example: Multi-Repo Changelog

When PRs from multiple repos get merged:

```
# Changelog v1.2.3

## Frontend (PR #42)
- Added dark mode toggle to user dashboard
- Fixed mobile responsive layout on tablet devices
- IMPACT: MINOR (feature addition)

## Backend (PR #88)
- Migrated authentication from JWT to OAuth 2.0
- Updated database schema for user profiles
- IMPACT: MAJOR (workflow change - review required!)

## Shared Library (PR #15)
- Fixed memory leak in cache utility function
- Updated TypeScript definitions
- IMPACT: PATCH (bug fix)
```

All in **one file**, **one version number**, **from three different repos**.

---

## ⚡ Setup & Step-by-Step

### Before You Start

Make sure you have:
- Docker & Docker Compose installed
- A GitHub account with a repo
- 15 minutes of free time
- Your brain ready to copy-paste commands (jokes aside, this is straightforward)

### Step 1: Clone and Configure

```bash
# Clone the repo
git clone https://github.com/PTejasKr/Capsule.git
cd Capsule

# Copy the example env file
cp .env.example .env

# Open .env in your editor
nano .env  # or vim, or your favorite editor
```

### Step 2: Get Your API Keys

You need 3 keys. Go grab them:

#### 🔑 GitHub Token

1. Go to GitHub → Settings → Developer Settings → Personal Access Tokens (classic)
2. Click "Generate new token"
3. Name it `Capsule` or something memorable
4. Check these boxes:
   - ✅ `repo` (full control of repos)
   - ✅ `workflow` (update workflows)
   - ✅ `admin:repo_hook` (manage webhooks)
5. Generate and copy the token (you'll only see it once!)
6. Paste in `.env`:
   ```
   GITHUB_TOKEN=ghp_your_token_here
   ```

#### 🔐 Webhook Secret

Generate a random string (the system will use this to verify GitHub really sent the webhook):

```bash
# Mac/Linux
python3 -c "import secrets; print(secrets.token_hex(32))"

# Or just make one up (boring but works)
# Example: ab12cd34ef56gh78ij90kl12mn34op56
```

Paste in `.env`:
```
GITHUB_WEBHOOK_SECRET=your_random_string_here
```

#### 🚀 NVIDIA NIM API Key

1. Sign up at [NVIDIA NGC](https://ngc.nvidia.com)
2. Go to API Keys section
3. Generate a new key (starts with `nvapi-`)
4. Copy it to `.env`:
   ```
   NVIDIA_NIM_API_KEY=nvapi_your_key_here
   ```

#### 🔐 API Key for Chrome Extension

This is just a random string that the extension uses to authenticate:

```bash
# Generate one
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Example: KX5vJ8qWpZlM2nR9sT6uVwXyZa1bCdEf
```

Paste in `.env`:
```
API_KEY=your_generated_key_here
```

### Step 3: Set Your Release Repository

This is where Capsule will push changelog updates.

```
CHANGELOG_REPO=your-github-username/releases
```

(You can create this repo on GitHub, or let Capsule auto-create it - we handle both)

### Step 4: Your Business Rules Document

This file tells Capsule what your business cares about:

Create a file: `./brd/requirements.md`

```markdown
# Business Requirements Document

## Critical Workflows
- **Authentication**: Must use OAuth 2.0 with 2FA enabled
- **Payments**: Must integrate with Stripe (no custom payment logic)
- **Data Storage**: All PII must be encrypted with AES-256

## Code Standards
- Backend: FastAPI only (no Django, no Flask)
- Frontend: React 18+
- Database: PostgreSQL (no MongoDB)

## Approval Rules
- Changes to auth flow: Require security review
- Database schema changes: Require DBA approval
- Third-party integrations: Require CTO sign-off

## What NOT to do
- Don't remove Sentry error tracking
- Don't disable API rate limiting
- Don't add hardcoded credentials
```

Capsule will read this and warn if a PR violates any rules.

### Step 5: Start the Containers

```bash
# This starts PostgreSQL, Redis, the API, Celery worker, and Nginx
docker-compose up -d --build

# Watch the startup
docker-compose logs -f capsule-api-server

# You should see: "Capsule API Service successfully started and ready"
```

### Step 6: Verify Everything Works

```bash
# Check if the API is running
curl http://localhost:8000/api/health

# You should get back:
# {"status":"healthy","service":"Capsule PR Analyzer","version":"1.0.0"}
```

### Step 7: Install Chrome Extension

1. Open Chrome
2. Go to `chrome://extensions/`
3. Toggle "Developer mode" (top right)
4. Click "Load unpacked"
5. Select the `extension` folder in your Capsule directory
6. Click on the Capsule icon → Settings
7. Enter:
   - Backend URL: `http://localhost:8000`
   - API Key: (the one from `.env` → `API_KEY`)
8. Click Save

### Step 8: Set Up Jenkins (Optional but Recommended)

If you're using Jenkins (and most teams are):

1. Go to **Manage Jenkins** → **Manage Credentials**
2. Add a new credential:
   - Kind: "Username with password"
   - Username: `capsule-bot`
   - Password: (the API_KEY from your `.env`)
   - ID: `capsule-api-key`
3. Click Create

Then, in your GitHub repo:
1. Settings → Webhooks → Add webhook
2. URL: `http://your-jenkins-server/github-webhook/`
3. Content-type: `application/json`
4. Trigger: "Let me select individual events" → Check "Pull requests" and "Pushes"
5. Click Add webhook

Finally, copy the Jenkinsfile to your repo root:
```bash
cp jenkins/Jenkinsfile ./Jenkinsfile
```

---

## Environment Variables (The Reference)

| Variable | What It Does | Example |
|----------|------------|---------|
| `API_KEY` | Chrome extension auth token | `KX5vJ8qWpZlM2nR9sT6uVwXyZa1bCdEf` |
| `GITHUB_TOKEN` | Authenticate with GitHub API | `ghp_xxxxxxxxxxxx` |
| `GITHUB_WEBHOOK_SECRET` | Verify GitHub webhooks are legit | `ab12cd34ef56gh78ij90kl12mn34op56` |
| `CHANGELOG_REPO` | Where to push changelogs | `your-org/releases` |
| `NVIDIA_NIM_API_KEY` | Access NVIDIA LLM | `nvapi_xxxxxxxxxxxx` |
| `NVIDIA_NIM_BASE_URL` | NVIDIA API endpoint | `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_NIM_MODEL` | Which LLM to use | `meta/llama-3.1-70b-instruct` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://postgres:postgres@postgres:5432/capsule` |
| `REDIS_HOST` | Redis cache server | `redis` (in Docker, use service name) |
| `BRD_FILE_PATH` | Path to your business rules | `./brd/requirements.md` |
| `LOG_LEVEL` | How verbose the logs are | `INFO` (or `DEBUG` for troubleshooting) |

---

## Testing It Out

### Test 1: Create a Test PR

1. Fork the Capsule repo (or create a test repo)
2. Create a new branch: `git checkout -b test-capsule`
3. Make a small change (add a comment, update a line)
4. Push and create a PR
5. Check the PR page - you should see the Capsule badge
6. Click it to see the AI analysis

### Test 2: Check Backend Logs

```bash
docker-compose logs -f capsule-api-server
```

You should see requests coming in when you open the PR.

### Test 3: Merge and Check Changelog

1. Merge the PR to `main`
2. Check your release repo - `changelog.txt` should be updated automatically
3. Version number should be bumped

---

## Common Issues & Fixes

### "Chrome Extension says 'Connection Failed'"

**Problem**: Extension can't reach the backend.

**Fix**:
```bash
# 1. Check if API is running
curl http://localhost:8000/api/health

# 2. Check the backend URL in extension settings
# (Should be http://localhost:8000 for local setup)

# 3. Check firewall - port 8000 might be blocked
sudo lsof -i :8000  # See what's using port 8000

# 4. Restart the API
docker-compose restart capsule-api-server
```

### "No Changelog Generated"

**Problem**: You merged a PR but nothing happened.

**Fix**:
```bash
# 1. Verify CHANGELOG_REPO is set correctly in .env
grep CHANGELOG_REPO .env

# 2. Check GitHub token has repo access
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user

# 3. Check Celery worker logs
docker-compose logs capsule-celery-worker

# 4. Manually trigger changelog generation
curl -X POST http://localhost:8000/api/pr/1/generate-changelog \
  -H "X-API-Key: $API_KEY"
```

### "NVIDIA API Error"

**Problem**: `"Unable to connect to NVIDIA NIM"`

**Fix**:
```bash
# 1. Verify API key is correct
echo $NVIDIA_NIM_API_KEY

# 2. Test connectivity to NVIDIA
curl -H "Authorization: Bearer $NVIDIA_NIM_API_KEY" \
  https://integrate.api.nvidia.com/v1/models

# 3. Check if you've exceeded rate limits
# (Wait a few minutes if rate-limited)

# 4. Use debug logging
# Set LOG_LEVEL=DEBUG in .env and restart
docker-compose restart capsule-api-server
```

### "Jenkins Webhook Not Triggering"

**Problem**: You created a PR but Jenkins didn't run.

**Fix**:
```bash
# 1. Check webhook delivery logs in GitHub
# Settings → Webhooks → [Your Webhook] → Recent Deliveries

# 2. Test the webhook manually
curl -X POST http://your-jenkins-server/github-webhook/ \
  -H "Content-Type: application/json" \
  -d '{"action":"opened","pull_request":{"number":1}}'

# 3. Check Jenkins plugin is installed
# Manage Jenkins → Plugin Manager → Search "GitHub"
# Make sure "GitHub Integration Plugin" is installed

# 4. Verify Jenkins can be reached from GitHub
# Test: curl -I http://your-jenkins-server/github-webhook/
```

### "Database Connection Error"

**Problem**: `"Cannot connect to postgresql://localhost:5432"`

**Fix**:
```bash
# 1. Check if PostgreSQL container is running
docker-compose ps postgres

# 2. View container logs
docker-compose logs postgres

# 3. Force restart the database
docker-compose down -v  # WARNING: This deletes data!
docker-compose up -d

# 4. Check DATABASE_URL in .env is correct
# Should be: postgresql+asyncpg://postgres:postgres@postgres:5432/capsule
```

---

## For the Curious: How the AI Works

### The 8-Layer Anti-Hallucination Shield

Why we don't trust AI blindly:

1. **Temperature 0.1** - Keeps responses consistent, not creative
2. **Confidence scoring** - AI rates how sure it is (we ignore low-confidence findings)
3. **Fact grounding** - Cross-references findings against actual file changes
4. **BRD validation** - Only reports violations actually mentioned in your BRD
5. **File existence checks** - Verifies modified files actually exist
6. **Pattern matching** - Double-checks findings with regex patterns
7. **Human review prompts** - Flags findings for manual review if unsure
8. **Changelog validation** - Makes sure generated entries match actual changes

**Result**: You get AI analysis you can actually trust, not hallucinations.

---

## Multi-Repo Deep Dive

### How It Actually Works

Say you have 3 repos with these webhooks all pointing to the same Jenkins:

```
Frontend: https://github.com/acme/app-ui
  ↓ PR opened
  → Webhook to Jenkins

Backend: https://github.com/acme/app-api
  ↓ PR opened
  → Webhook to Jenkins

Shared: https://github.com/acme/app-shared
  ↓ PR opened
  → Webhook to Jenkins
```

When your team merges PRs to main across all 3 repos, Capsule:

1. **Collects all merged PRs** from PostgreSQL
2. **Retrieves cached analysis** from Redis (fast!)
3. **Aggregates results** - Groups by repo, calculates overall SemVer bump
4. **Generates consolidated changelog** - One entry per PR, organized by repo
5. **Bumps version** - Highest impact determines version bump (MAJOR > MINOR > PATCH)
6. **Pushes to release repo** - Updates `changelog.txt` with new version and all entries

### Data Flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant GH as GitHub
    participant Jenkins as Jenkins
    participant Cache as Redis Cache
    participant DB as PostgreSQL
    participant AI as NVIDIA LLM
    participant Release as Release Repo

    Dev->>GH: Open PR in app-ui
    GH->>Jenkins: Webhook
    Jenkins->>DB: Store PR metadata
    DB->>DB: Query BRD (business rules)
    Jenkins->>AI: Send PR diff + BRD
    AI-->>Jenkins: Analysis result
    Jenkins->>Cache: Store analysis (10 min TTL)
    GH->>GH: Show Capsule badge on PR

    Note over Dev: ... time passes ...
    
    Dev->>GH: Merge PR to main
    GH->>Jenkins: Webhook (PR merged)
    Jenkins->>DB: Query all merged PRs
    DB-->>Jenkins: List of merged PRs
    Jenkins->>Cache: Fetch cached analysis
    Cache-->>Jenkins: Analysis results
    Jenkins->>Jenkins: Aggregate + calculate SemVer
    Jenkins->>Release: Push changelog v1.2.3
    Release->>GH: Create commit + tag
```

---

## What's Next?

- **Self-host**: Run this on your own server instead of localhost
- **Custom AI models**: Swap NVIDIA LLM for your own model
- **Slack notifications**: Get alerts when high-impact PRs are analyzed
- **Policy enforcement**: Automatically block merges that violate rules

---

## Help & Support

### Find an Issue?

1. Check [existing issues](https://github.com/PTejasKr/Capsule/issues)
2. Create a new issue with:
   - What you were trying to do
   - What happened
   - Full error message (screenshot is fine)
   - Your setup (Docker? Jenkins version? etc.)

### Want to Contribute?

- Fork the repo
- Create a feature branch
- Make your changes
- Submit a PR

We read all submissions! 🙏

---

## License

MIT - Do whatever you want with this, just don't blame us if it breaks production. (Just kidding, please test first.)

---

**Made by engineers, for engineers.**

*Questions? Issues? Ideas? Create an issue or start a discussion. We're here to help.*

**Latest version**: 1.0.0 | **Last updated**: 2026 | **Status**: ✅ Production Ready
