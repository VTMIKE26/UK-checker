# 🦅 Peregrine Daily Federal Scanner

Automated daily intelligence tool for Peregrine.io — searches federal procurement databases, agency budget signals, competitive intelligence, and grant funding every weekday morning and delivers a ranked HTML digest by email.

---

## What It Does

Every weekday at 7:00 AM EST, the scanner:

1. Searches **10+ federal data sources** for active opportunities
2. Scores every result against **9 capability clusters** and **249 hard exclusions**
3. Ranks results into Strong / Good / Possible / Low Fit tiers
4. Delivers a formatted HTML email digest with Why It Fits reasoning for every result
5. Surfaces competitive intelligence, agency budget signals, and relevant grants

---

## Scoring System

Every opportunity is scored against Peregrine's 9 capability clusters. The total score determines its tier.

| Cluster | Points | Signal |
|---|---|---|
| Data Integration & Unification | 20 | Enterprise data platforms, unified environments |
| Investigative & Operational Analytics | 20 | Crime analytics, digital evidence, link analysis |
| Federated & Enterprise Search | 20 | Cross-system search, query federation |
| Entity Resolution & Record Intelligence | 20 | Deduplication, identity resolution, record linking |
| Secure Government SaaS | 15 | FedRAMP, CJIS, GovCloud, Zero Trust |
| Public Safety & Law Enforcement | 20 | LE platforms, NIBIN, fusion centers, RMS |
| Corrections & Community Supervision | 20 | Probation, parole, CSOSA, offender management |
| Platform Modernization & Replacement | 20 | Palantir replacement, legacy modernization |
| AI & Machine Learning | 22 | AI/ML platforms, predictive analytics, LLMs |

### Tier Thresholds

| Tier | Score | Action |
|---|---|---|
| 🟢 Strong Fit | ≥ 40 pts | Act Now |
| 🟡 Good Fit | ≥ 15 pts | Review Today |
| 🔵 Possible Fit | > 0 pts | Review These |
| ⚪ Low Fit | 0 pts | Any keyword match |
| ⛔ Excluded | — | Hard exclusion matched |

### Hard Exclusions

249 terms across 20 categories immediately disqualify an opportunity before scoring runs: physical facilities, military hardware, aircraft/weapons systems, network/telecom infrastructure, maintenance agreements, equipment rental, medical/pharma, staffing-only, security guard services, physical training, treatment courts, victim services, social services, research-only grants, and more.

---

## Data Sources (10 active)

### 🔵 SAM.gov API *(requires free API key)*
Primary federal procurement database. Two-pass approach:
- **Pass 1 — 6 ptype sweeps** (30-day window): Sources Sought (`r`), Presolicitation (`p`), Combined Synopsis (`k`), Special Notice (`s`), Solicitation (`o`), Intent to Bundle (`i`)
- **Pass 2 — 16 title searches** (90-day window): paginated (2 pages × 100 results) for high-volume terms like "artificial intelligence" and "data analytics" to avoid the 100-result hard cap

Results cached in `_SAM_RESULTS_CACHE` so DOJ/DHS/DoD can filter without additional API calls.

### 🏛 DOJ — Department of Justice
Post-filters the SAM cache by `fullParentPathName` for: Department of Justice, ATF, FBI, DEA, BOP, OJP, CSOSA, COPS Office, USMS, NSD, EOUSA. 43 capability-mapped search terms. **Zero additional API calls.**

### 🛡️ DHS — Department of Homeland Security
Post-filters the SAM cache for: CBP, ICE/HSI, USCG, CISA, FEMA, TSA, USSS, USCIS, FLETC, I&A, S&T. Same 43-term search. **Zero additional API calls.**

### ⚔️ DoD — Department of Defense
Post-filters the SAM cache for DoD agencies with enterprise data/AI needs: National Guard Bureau, DISA, DIA, DLA, Army, Navy, Air Force, Space Force, OSD. Catches programs like the NGB Enterprise Data & AI Modernization RFI. **Zero additional API calls.**

### 📰 Federal Register API *(no key required)*
Official U.S. government journal. Searches 8 targeted keyword queries for RFI/Sources Sought signal words in a 10-day window.

### 💰 USASpending.gov *(no key required)*
Competitive intelligence on recent contract awards across 6 keyword batches. Results appear in the Award Intel section, separate from opportunity tiers.

### 📡 Agency RSS Feeds
Industry news from FedScoop, Nextgov, GovTech Public Safety, GCN, Police1, Corrections1.

### 🎤 Events Intelligence
20+ curated events plus live RSS feeds. Filtered to next 3 months.

### 🔎 Competitor Intelligence
Per-competitor Google News RSS queries for all 12 tracked competitors. Targeted by name to prevent false multi-competitor attribution. Max 2 articles per competitor per day.

### 💵 Federal Funding
Targeted grants.gov + Federal Register searches using specific compound phrases. Excludes treatment courts, victim services, social services, and all non-technology programs. Includes "Why It Fits" reasoning mapped to Peregrine capabilities and customer types.

---

## Email Digest Sections

| Section | Content |
|---|---|
| 🟢 Strong Fit — Act Now | ≥ 40 pts with Why It Fits |
| 🟡 Good Fit — Review Today | ≥ 15 pts |
| 🔵 Possible Fit | > 0 pts |
| ⚪ Low Fit | 0 pts, any keyword match |
| 📊 Award Intel | Top 5 USASpending recent awards (competitive intel) |
| 🎯 Palantir Recompetes | Palantir contracts expiring within 12 months |
| ⚡ Other Competitor Recompetes | Axon, Tyler, Motorola, Mark43, IBM i2, ShotSpotter, Flock Safety |
| ⚔️ Competitor News | Max 2 articles per competitor, Google News sourced |
| 💰 Federal Funding | Direct tech grants + customer budget signals with Why It Fits |
| 📡 Agency Budget Signals | Recent budget/spending news at DOJ, DHS, DoD sub-agencies |
| 📰 Industry News | Market signals from govtech/LE media |
| 🎤 Events & Conferences | Next 3 months only |

Subject line format: `Peregrine Daily Scanner | 3 Strong · 5 Good · 8 Possible | Apr 28`

---

## Competitors Monitored (12)

Palantir · Axon · ShotSpotter · Mark43 · Tyler Technologies · Motorola Solutions · IBM i2 · Esri · Databricks · Appriss · SuperCom · Flock Safety

USASpending recompete tracking: Palantir, Axon, Tyler Technologies, Motorola Solutions, Mark43, IBM i2, ShotSpotter, Flock Safety

---

## Setup

### Step 1 — SAM.gov API key (free)
1. Sign in at [sam.gov](https://sam.gov)
2. Go to **Profile → API Keys → Generate Key**

### Step 2 — SendGrid API key (free tier, 100 emails/day)
1. Sign up at [sendgrid.com](https://sendgrid.com)
2. **Settings → API Keys → Create API Key** → Restricted → Mail Send only

### Step 3 — GitHub Secrets
Go to **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `SAM_API_KEY` | Your SAM.gov API key |
| `SENDGRID_API_KEY` | Your SendGrid API key |

### Step 4 — Reliable scheduling via cron-job.org

GitHub Actions cron is unreliable (30–90 min delays common). Use [cron-job.org](https://cron-job.org) (free) as the primary trigger:

**cron-job.org settings:**
- **URL**: `https://api.github.com/repos/VTMIKE26/daily-Opps-Check/actions/workflows/daily_scan.yml/dispatches`
- **Method**: POST
- **Headers**: `Authorization: token YOUR_GITHUB_PAT` · `Accept: application/vnd.github+json` · `Content-Type: application/json`
- **Body**: `{"ref":"main"}`
- **Schedule**: `0 12 * * 1-5` (7am EST) AND `0 11 * * 1-5` (7am EDT)

Generate a GitHub PAT at [github.com/settings/tokens](https://github.com/settings/tokens) with `repo` + `workflow` scopes. A successful test run returns HTTP **204**.

The GitHub native cron at `20 12 * * 1-5` (7:20 AM) stays as a backup. The concurrency group `peregrine-daily-scanner` prevents duplicate emails if both fire.

---

## Running Locally

```bash
pip install requests

export SAM_API_KEY="your_key_here"
export SENDGRID_API_KEY="your_sendgrid_key"
export EMAIL_TO="mike.kelly@peregrine.io"
export EMAIL_FROM="mikefkelly26@gmail.com"

python daily_scan.py
```

Output: `digest_YYYYMMDD.html` saved locally. Expected runtime: ~2 minutes.

---

## API Rate Limits

| API | Daily Limit | Our Usage |
|---|---|---|
| SAM.gov | 1,000 calls/day | ~390 calls |
| Federal Register | Unlimited | ~8 calls |
| USASpending.gov | Unlimited | ~6 calls |
| grants.gov | Unlimited | ~35 calls |
| Google News RSS | Unlimited | ~30 feeds |
| SendGrid (free) | 100 emails/day | 1 email |

---

## File Structure

```
daily-Opps-Check/
├── daily_scan.py               # Main script — all sources, scoring, email
├── .github/
│   └── workflows/
│       ├── daily_scan.yml      # Primary workflow (dispatch + 7:20am backup cron)
│       └── keep_alive.yml      # Commits timestamp to prevent 60-day inactivity suspension
└── README.md
```
