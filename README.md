# 🦅 Peregrine UK Daily Scanner

Automated daily procurement intelligence tool for Peregrine.io's UK colleagues — searches UK public procurement databases every weekday morning and delivers a ranked HTML digest by email.

---

## What It Does

Every weekday at 7:00 AM GMT/BST, the scanner:

1. Searches **UK Find a Tender** and **Contracts Finder** for active procurement notices
2. Scores every result against **9 capability clusters** and **UK-specific hard exclusions**
3. Ranks into Strong / Good / Possible / Low Fit tiers with **Why It Fits** reasoning
4. Surfaces **UK competitor intelligence** (15 competitors including UK-native players)
5. Delivers a formatted HTML email digest

---

## Scoring System

Same 9 clusters as the US scanner, tuned for UK terminology:

| Cluster | Points | UK Signal |
|---|---|---|
| Data Integration & Unification | 20 | Enterprise data platforms, data harmonisation |
| Investigative & Operational Analytics | 20 | Crime analytics, BWV analytics, digital forensics |
| Federated & Enterprise Search | 20 | Cross-system search, multi-source intelligence |
| Entity Resolution & Record Intelligence | 20 | Record deduplication, identity matching |
| Secure Government SaaS | 15 | Cyber Essentials, G-Cloud, IL2/IL3, ISO 27001 |
| Public Safety & Law Enforcement | 20 | Police analytics, ANPR, NIM, custody management |
| Corrections & Community Supervision | 20 | HMPPS, probation, electronic monitoring, YOT |
| Platform Modernisation & Replacement | 20 | Legacy modernisation, digital transformation |
| AI & Machine Learning | 22 | AI/ML platforms, predictive policing, NLP |

### Tier Thresholds
| Tier | Score | Action |
|---|---|---|
| 🟢 Strong Fit | ≥ 40 pts | Act Now |
| 🟡 Good Fit | ≥ 15 pts | Review Today |
| 🔵 Possible Fit | > 0 pts | Review These |
| ⚪ Low Fit | 0 pts | Any keyword match |

### CPV Code Intelligence
The scanner uses EU Common Procurement Vocabulary codes (mandatory on UK tenders) to boost relevance. CPV prefixes 722–729 (IT services), 480–489 (software), and 752 (law enforcement) are treated as inherently relevant regardless of title.

### Hard Exclusions
50+ terms covering: physical facilities, construction, catering, uniforms, hardware-only procurement, military equipment, network cabling, maintenance agreements, staffing, treatment services, domestic abuse refuges, training-only contracts.

---

## Data Sources

### 🔵 Find a Tender Service (FTS)
UK government's official above-threshold procurement portal. Uses the **OCDS release packages API** — no API key required, Open Government Licence.

- **Endpoint**: `https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages`
- **Filter**: `stages=tender`, 30-day window, paginated via cursor
- **Format**: OCDS JSON — title, buyer, CPV code, deadline, value (GBP), description
- **Coverage**: England, Wales, Northern Ireland, Scotland (above threshold)
- **Threshold**: Generally £139,688+ incl. VAT (Procurement Act 2023)

### 🔵 Contracts Finder
Below-threshold opportunities in England. Keyword searches via OCDS API — no key required.

- **Endpoint**: `https://www.contractsfinder.service.gov.uk/Published/Notice/OCDS/Search`
- **Coverage**: England, generally £12,000–£139,688
- **Searches**: 21 capability-matched keyword terms

### 🔎 UK Competitor Intelligence
Google News UK edition (`.../ceid=GB:en`) per competitor, 2 articles max per competitor:

**US players with major UK presence:**
Palantir UK · Axon UK · Motorola Solutions · IBM i2 · Databricks

**UK-native and Europe-based competitors:**
Civica · NEC UK · Hexagon · NICE Systems · Capita · Sopra Steria · CGI UK · Vigil AI · Forensic Analytics · i-nexus

### 📰 UK Industry News
PublicTechnology · PoliceOracle · GOV.UK (policing + CJ tech feeds) · LGC · Computer Weekly · UKAuthority · StateScoop · DefenseScoop

---

## UK Procurement Context

**Procurement Act 2023** (in force 24 February 2025) governs new procurements in England, Wales, and Northern Ireland. Scotland uses the Public Contracts (Scotland) Regulations 2015.

**Key UK buyer agencies for Peregrine:**
- Home Office (policing strategy, immigration enforcement)
- National Police Chiefs' Council (NPCC)
- 43 territorial police forces in England & Wales
- Police Scotland
- Police Service of Northern Ireland (PSNI)
- Ministry of Justice / His Majesty's Prison and Probation Service (HMPPS)
- National Probation Service
- Crown Prosecution Service (CPS)
- National Crime Agency (NCA)
- Serious Fraud Office (SFO)
- UK Border Force / Immigration Enforcement
- HM Revenue & Customs (HMRC) — Fraud Investigation Service
- Crown Commercial Service (CCS) — framework agreements

**Key procurement frameworks (Peregrine-relevant):**
- **G-Cloud 14** — cloud software and services, CDPS marketplace
- **RM6261 (Technology Products & Services)** — Crown Commercial Service
- **DOS6 (Digital Outcomes and Specialists)** — CDPS
- **RM6068 (Data & Application Solutions)**

---

## Setup

### Step 1 — GitHub Secrets

Add these to **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `SENDGRID_API_KEY` | Your SendGrid API key (same as US scanner) |
| `UK_EMAIL_TO` | UK team email address |
| `EMAIL_FROM` | Sender email address |

> No SAM.gov key needed — Find a Tender and Contracts Finder are both open APIs.

### Step 2 — Reliable scheduling via cron-job.org

GitHub Actions cron is unreliable. Use [cron-job.org](https://cron-job.org) (free):

**cron-job.org settings:**
- **URL**: `https://api.github.com/repos/YOUR_ORG/YOUR_REPO/actions/workflows/uk_daily_scan.yml/dispatches`
- **Method**: POST
- **Headers**: `Authorization: token YOUR_PAT` · `Accept: application/vnd.github+json` · `Content-Type: application/json`
- **Body**: `{"ref":"main"}`
- **Schedule (GMT, Nov–Mar)**: `0 7 * * 1-5`
- **Schedule (BST, Mar–Oct)**: `0 6 * * 1-5`

Create both — BST is UTC+1 so the summer cron is `0 6` and winter is `0 7`.

Generate a GitHub PAT at [github.com/settings/tokens](https://github.com/settings/tokens) with `repo` + `workflow` scopes. A successful test returns HTTP **204**.

### Step 3 — Keep workflows alive

`keep_alive.yml` commits a timestamp every weekday at 7:00 AM GMT, preventing GitHub disabling scheduled workflows after 60 days of inactivity.

---

## Running Locally

```bash
pip install requests

export SENDGRID_API_KEY="your_sendgrid_key"
export EMAIL_TO="your-uk-team@peregrine.io"
export EMAIL_FROM="scanner@peregrine.io"

python uk_daily_scan.py
```

Output: `uk_digest_YYYYMMDD.html` saved locally. Open in browser to preview.

**Expected runtime:** ~2–3 minutes (no API rate limits on FTS or Contracts Finder).

---

## File Structure

```
peregrine-uk-scanner/
├── uk_daily_scan.py            # Main script
├── .github/
│   └── workflows/
│       ├── uk_daily_scan.yml   # Primary workflow (dispatch + 7:20am backup)
│       └── keep_alive.yml      # Prevents 60-day inactivity suspension
└── README.md
```

---

## API Limits

| API | Rate Limit | Our Usage |
|---|---|---|
| Find a Tender OCDS | 429 with Retry-After header | ~5–10 paginated calls |
| Contracts Finder | None documented | ~21 keyword calls |
| Google News RSS | Informal | ~30 feeds |
| SendGrid (free) | 100 emails/day | 1 email |

---

## Differences from US Scanner

| Feature | US Scanner | UK Scanner |
|---|---|---|
| Primary source | SAM.gov (API key required) | Find a Tender (no key) |
| Secondary source | Contracts Finder (US) | Contracts Finder (UK) |
| Agency filters | DOJ, DHS, DoD | Not required — all UK buyers |
| Scoring terminology | Modernization, FedRAMP, CJIS | Modernisation, G-Cloud, Cyber Essentials |
| Competitors | 12 (US-focused) | 15 (includes Civica, NEC, Hexagon, Capita, CGI) |
| Date format | MM/DD/YYYY | DD Month YYYY (UK standard) |
| Currency | USD | GBP |
| Time zone | EST/EDT | GMT/BST |
| Procurement law | FAR / SAM.gov | Procurement Act 2023 / OJEU/FTS |
