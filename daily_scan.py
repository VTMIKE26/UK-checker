#!/usr/bin/env python3
"""
Peregrine.io Daily Federal Opportunity Scanner — Multi-Source Edition
=======================================================================
Data Sources (all free, no registration required except SAM.gov API):
  1. SAM.gov API v2          — RFIs, Sources Sought, Pre-Solicitations, Industry Days
  2. Federal Register API    — RFI notices published by federal agencies (NO KEY)
  3. USASpending.gov API v2  — Recent contract awards in target NAICS (competitive intel) (NO KEY)
  4. DHS/DOJ/FBI procurement — Web-scraped upcoming solicitations & industry events
  5. GSA eBuy / schedules    — RSS/public feed scrape for IT Schedule 70 opportunities

Outputs:
  - Ranked HTML email digest sent to configured recipients
  - Local HTML file saved for auditing
"""

import os
import re
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from html import unescape
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# CONFIGURATION — only 3 secrets needed
# ---------------------------------------------------------------------------
SAM_API_KEY       = os.environ.get("SAM_API_KEY", "")
SENDGRID_API_KEY  = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_TO          = os.environ.get("EMAIL_TO", "mike.kelly@peregrine.io")
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "mike.kelly@peregrine.io")

# Debug output — printed in GitHub Actions logs (secrets are masked automatically)
print(f"[Config] SAM_API_KEY set:      {'YES' if SAM_API_KEY else 'NO - SAM.gov results will be empty'}")
print(f"[Config] SENDGRID_API_KEY set: {'YES' if SENDGRID_API_KEY else 'NO - will fail at send step'}")
print(f"[Config] EMAIL_TO:             {EMAIL_TO}")
print(f"[Config] EMAIL_FROM:           {EMAIL_FROM}")

HEADERS = {
    "User-Agent": "PeregrineOpportunityScanner/2.0 (federal procurement research; contact@peregrine.io)",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# PEREGRINE CORE CAPABILITIES (grounded in actual product)
#
# Peregrine is a secure enterprise data integration and intelligence platform
# purpose-built for law enforcement, public safety, and corrections agencies.
# It does NOT provide: hardware, staffing, maintenance, construction, or
# general IT helpdesk. It IS: a SaaS data platform with analytics.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DATA CLASS
# ---------------------------------------------------------------------------
from dataclasses import dataclass, field as dc_field

@dataclass
class Opportunity:
    title: str
    notice_id: str
    agency: str
    posted_date: str
    response_date: str
    description: str
    url: str
    opp_type: str
    source: str
    naics: str = ""
    score: int = 0
    score_reasons: list = dc_field(default_factory=list)
    tier: str = ""


# ---------------------------------------------------------------------------
# DATE UTILITIES
# ---------------------------------------------------------------------------
def parse_date_flexible(date_str: str):
    """Try multiple date formats and return a datetime or None."""
    if not date_str or date_str in ("TBD", "N/A", "See posting",
            "Watch for recompete", "See event page for registration deadline",
            "Monitor for follow-on procurement"):
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %b %Y",
    ]
    clean = date_str.strip()[:25]
    for fmt in fmts:
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None

def is_expired(opp) -> bool:
    """
    Return True ONLY if the response deadline has clearly passed.
    Only checks response_date — never posted_date (which is always in the past).
    If response_date is TBD/unparseable, assume still active.
    """
    grace = datetime.utcnow() - timedelta(days=2)
    dt = parse_date_flexible(opp.response_date)
    if dt:
        return dt < grace
    # TBD or unparseable deadline = assume still open
    return False

def clean_url(url: str, fallback: str = "") -> str:
    """
    Validate and clean a URL. Returns the URL if valid, fallback otherwise.
    Ensures URLs start with http/https, strips whitespace, and handles
    common malformed patterns from API responses.
    """
    if not url:
        return fallback
    url = url.strip()
    # Must start with http or https
    if not url.startswith(("http://", "https://")):
        # Try prepending https
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("www."):
            url = "https://" + url
        else:
            return fallback
    # Basic sanity — no spaces, reasonable length
    if " " in url or len(url) > 2000:
        return fallback
    return url


# Peregrine's 6 core capability areas — what it actually sells and deploys
CAPABILITY_CLUSTERS = [
    (
        # Peregrine unifies siloed data from multiple systems into one platform
        "Data Integration & Unification", 20,
        [
            # Core phrases
            "data integration", "data unification", "data fusion",
            "disparate systems", "disparate data", "data silos",
            "siloed data", "data harmonization", "fragmented data",
            "enterprise data platform", "data integration platform",
            "unified data", "unified platform", "data consolidation",
            "information integration", "information sharing",
            "master data management", "data normalization",
            "data ingestion", "data pipeline", "data fabric",
            "data lake", "data warehouse", "data mesh",
            # Shorter triggers that appear in real titles
            "data analytics", "analytics platform", "analytics tool",
            "data management", "data management platform",
            "data management system", "data solution",
            "data platform", "data environment",
            "analytics solution", "analytics service",
            "reporting tool", "reporting platform",
            "dashboard", "business intelligence",
            "software platform", "enterprise software",
            "cloud platform", "cloud solution", "cloud-based",
        ],
    ),
    (
        # Peregrine surfaces connections, patterns, and insights for investigators
        "Investigative & Operational Analytics", 20,
        [
            # Core phrases
            "investigative analytics", "investigative platform",
            "investigative tool", "investigative system",
            "link analysis", "relationship mapping",
            "situational awareness", "operational intelligence",
            "operational dashboard", "pattern of life",
            "geospatial analysis", "geospatial intelligence",
            "crime analytics", "crime analysis",
            "advanced analytics", "intelligence platform",
            "intelligence system", "real-time analytics",
            "predictive analytics", "predictive policing",
            "common operating picture",
            # Shorter triggers
            "investigation management", "case analytics",
            "operational analysis", "mission analytics",
            "visualization", "geospatial", "mapping platform",
            "predictive", "intelligence analysis",
            # Digital evidence — DOJ DERP and similar platforms
            "digital evidence", "evidence review platform",
            "evidence analytics", "evidence management platform",
            "media review platform", "digital forensics platform",
            "investigative data platform",
        ],
    ),
    (
        # Peregrine lets users search across multiple connected systems at once
        "Federated & Enterprise Search", 20,
        [
            "federated search", "enterprise search",
            "cross-system search", "unified search",
            "search across", "search multiple",
            "search and retrieval", "information retrieval",
            "search capability", "search platform",
            "search solution", "search system",
            "knowledge retrieval", "query across",
            "semantic search", "full-text search",
            "document search", "content search",
        ],
    ),
    (
        # Peregrine deduplicates and resolves records across systems
        "Entity Resolution & Record Intelligence", 20,
        [
            "entity resolution", "record deduplication",
            "record linkage", "duplicate records",
            "identity resolution", "entity matching",
            "data deduplication", "entity-centric",
            "record consolidation", "ontology",
            "knowledge graph", "graph analytics",
            "relationship graph", "master record",
            "person record", "record resolution",
            "deduplication", "entity management",
        ],
    ),
    (
        # Peregrine is FedRAMP-authorized, CJIS-compliant, runs on AWS GovCloud
        "Secure Government SaaS", 15,
        [
            "fedramp", "cjis", "nist 800-53", "nist sp 800",
            "govcloud", "zero trust", "icam",
            "saml", "single sign-on", "sso",
            "role-based access", "rbac",
            "attribute-based access", "abac",
            "section 508", "audit logging",
            "authority to operate", "ato",
            "cloud security", "secure cloud",
            "government cloud", "cloud compliance",
        ],
    ),
    (
        # Public Safety & Law Enforcement — must imply SOFTWARE/DATA need,
        # not just any law enforcement adjacent work. "police" alone matches
        # vehicle purchases, uniforms, etc. Require compound terms that signal
        # a technology or data platform requirement.
        "Public Safety & Law Enforcement", 20,
        [
            # Specific Peregrine integrations (always relevant)
            "nibin", "etrace", "crime gun", "ballistic intelligence",
            "cgic", "crime gun intelligence",
            # Platform/system terms — imply software procurement
            "records management system", "records management software",
            "computer-aided dispatch", "computer aided dispatch", "cad system", "cad software",
            "law enforcement platform", "law enforcement software",
            "law enforcement analytics", "law enforcement data",
            "law enforcement technology", "law enforcement information",
            "public safety platform", "public safety software",
            "public safety technology", "public safety data",
            "public safety analytics", "public safety system",
            "policing platform", "policing software",
            "fusion center", "fusion center platform",
            "criminal justice platform", "criminal justice software",
            "criminal justice information system", "criminal justice data",
            "crime analytics", "crime data", "crime intelligence",
            "evidence management system", "evidence management platform",
            "investigation platform", "investigative software",
            "body camera data", "body camera analytics",
        ],
    ),
    (
        # Peregrine is deployed for probation/parole agencies (CSOSA use case)
        "Corrections & Community Supervision", 20,
        [
            "community supervision", "probation", "parole",
            "reentry", "offender management",
            "supervision officer", "court services",
            "pretrial", "case supervision",
            "csosa", "bureau of prisons",
            "department of corrections",
            "recidivism", "offender data",
            "supervision platform", "smart21",
            "supervised release",
            "correctional software", "correctional platform",
            "correctional data", "correctional analytics",
            "offender tracking", "supervision software",
            "supervision system", "case management",
            "supervision platform", "supervision system", "supervision software",
            "supervision analytics", "offender supervision",
        ],
    ),
    (
        # Peregrine replaces legacy and incumbent platforms like Palantir
        "Platform Modernization & Replacement", 20,
        [
            "palantir", "palantir replacement",
            "palantir alternative", "gotham", "foundry",
            "ibm i2", "platform replacement",
            "incumbent replacement", "platform consolidation",
            "legacy platform", "legacy system",
            "legacy modernization", "platform modernization",
            "platform migration", "technology refresh",
            "system modernization",             "data platform upgrade",
            "it modernization", "digital transformation",
            "software modernization", "cloud migration",
            "application modernization",
            "platform modernization", "legacy modernization",
            "system modernization", "data modernization",
            "technology modernization", "network modernization",
        ],
    ),
    (
        # Peregrine embeds AI/ML for investigative decision support
        "AI & Machine Learning", 22,
        [
            "artificial intelligence", "machine learning",
            "ai/ml", "ai platform", "ai solution",
            "ai system", "ai services",
            # Space-padded to prevent substring matches like "regenerative" → "generative ai"
            " generative ai", "generative ai ",
            "large language model", "llm",
            "natural language processing", "nlp",
            "computer vision", "predictive model",
            "decision support", "decision support system",
            "automated analysis", "intelligent automation",
            "ai-powered", "ai-driven",
            "ai for law enforcement", "ai public safety",
            "responsible ai", "explainable ai",
            "ai governance", "ai analytics",
        ],
    ),
]

# NAICS hints — infer capability when SAM.gov description is blank

# Hard exclusions — ONLY work that has zero software/data component
# Keep very specific to avoid blocking legitimate IT solicitations
HARD_EXCLUSIONS = [
    # Maintenance & repair (the big new addition)
    "maintenance and repair", "repair and maintenance", "maintenance services only",
    "equipment repair", "equipment maintenance", "preventive maintenance",
    "corrective maintenance", "vehicle repair", "vehicle maintenance",
    "facility maintenance", "building maintenance", "hvac maintenance",
    "elevator maintenance", "generator maintenance", "engine repair",
    "aircraft maintenance", "ship repair", "vessel maintenance",
    # Physical facilities
    "janitorial services", "landscaping services", "custodial services",
    "grounds maintenance", "pest control services", "roofing services",
    "flooring installation", "plumbing services", "painting services",
    # Hardware-only procurement (specific phrases)
    "hardware procurement", "hardware purchase", "purchase of laptops",
    "purchase of desktops", "purchase of servers", "purchase of tablets",
    "network cabling", "structured cabling", "body-worn camera purchase",
    "body camera hardware", "purchase of radios", "radio hardware",
    "purchase of body armor", "ballistic vest", "purchase of firearms",
    "ammunition procurement", "vehicle purchase", "fleet vehicle acquisition",
    "drone procurement", "uav procurement", "sensor hardware purchase",
    # Food & clothing
    "food service contract", "food supply", "clothing procurement",
    "uniform procurement", "laundry services",
    # Medical / pharma (non-IT)
    "pharmaceutical procurement", "drug manufacturing", "medical supply",
    "laboratory reagent", "clinical trial services",
    # Construction & infrastructure projects
    "construction project", "construction contract", "construction services",
    "design and construction", "build and construction", "new construction",
    "renovation project", "renovation contract", "building renovation",
    "infrastructure construction", "facility construction",
    "construction management", "general contractor",
    "design-build", "design build", "architect and engineer",
    # Logistics
    "refuse collection", "moving services", "freight services",
    "shipping contract",
    # Professional services unrelated to Peregrine
    "translation services", "interpretation services",
    "attorney services", "legal representation",
    "financial audit services", "accounting services",
    # Hardware & equipment procurement — Peregrine is software only
    "purchase of equipment", "equipment procurement", "equipment acquisition",
    "hardware and equipment", "purchase hardware",
    "body armor", "protective equipment procurement",
    "weapon system", "weapons system", "small arms",
    "radio procurement", "radio acquisition", "portable radio",
    "vehicle acquisition", "vehicle procurement", "fleet acquisition",
    "license plate reader", "lpr procurement",
    "surveillance camera", "camera system procurement",
    "biometric device", "biometric hardware",
    "taser procurement", "less lethal",
    "furniture procurement", "office furniture",
    "it equipment purchase", "computer equipment purchase",
    "printer procurement", "copier procurement",
    "mobile device procurement", "tablet procurement",
    # Staffing-only contracts
    "staffing services", "staff augmentation", "labor category",
    "temporary staffing", "personnel services contract",
    "security guard", "guard services", "physical security services",
    # Training-only (not software training)
    "firearms training", "defensive tactics", "use of force training",
    "physical fitness", "k-9 training", "canine training",
    # Equipment rental and physical goods
    "equipment rental", "rental of equipment", "equipment lease",
    "air compressor", "generator rental", "forklift rental",
    "heavy equipment", "construction equipment",
    "medical equipment", "laboratory equipment",
    "audio visual equipment", "av equipment",
    "office equipment rental",
    # Physical goods procurement
    "purchase of supplies", "office supplies",
    "janitorial supplies", "cleaning supplies",
    # Hardware devices — tablets, phones, computers
    "tablets", "tablet procurement", "tablet purchase",
    "mobile devices", "smartphones", "cell phones",
    "laptops", "desktops", "workstations",
    "printers", "copiers", "scanners",
    # Physical facilities and infrastructure — not software
    "fire suppression", "fire alarm", "fire protection",
    "audio system", "audio visual", "av system",
    "hvac", "plumbing", "electrical system",
    "roof replacement", "flooring replacement", "window replacement",
    "elevator", "escalator", "generator replacement",
    "lighting system", "lighting replacement",
    "physical security system", "access control hardware",
    "camera installation", "cctv installation",
    # Maintenance contracts — not software development
    "annual maintenance", "annual software maintenance",
    "software maintenance agreement", "maintenance and support contract",
    "hardware maintenance", "software assurance",
    # Embassy / consular / facilities
    "embassy", "consular", "chancery",
    # Military hardware, aircraft, weapons systems — not Peregrine's market
    "crypto modernization", "cryptographic", "encryption hardware",
    "router solution", "b-52", "aircraft", "avionics",
    "missile", "munitions", "ammunition", "ordnance",
    "radar", "sonar", "weapons system", "armament",
    "c-130", "f-35", "v-22", "helicopter",
    "ship", "submarine", "vessel",
    "military vehicle", "tactical vehicle",
    # Network / telecom / infrastructure — not software
    "vpn", "ethernet", "transport services", "network infrastructure",
    "telecommunications", "telecom services", "internet service provider",
    "network cabling", "structured cabling", "fiber optic",
    "wireless network", "cellular services", "satellite services",
    "bandwidth services", "circuit services", "wan services",
    "network connectivity", "connectivity services",
    # Hardware support & maintenance agreements — not software
    "maintenance agreement", "service agreement hardware",
    "network server", "server maintenance", "server hardware",
    "hardware support", "hardware maintenance agreement",
    "pma maintenance", "preventive maintenance agreement",
    "network equipment", "server equipment",
    "storage hardware", "storage array",
    "firewall hardware", "switch hardware", "router hardware",
    "data center hardware", "rack hardware",
]

# Penalty signals — mismatch indicators (reduce score but don't exclude)
PENALTY_SIGNALS = [
    ("staffing augmentation", -8),
    ("time and materials labor", -6),
    ("independent verification and validation", -6),
    ("iv&v services", -6),
    ("penetration testing only", -5),
]

# NAICS prefix → capability hints for scoring when description is blank
NAICS_CAPABILITY_HINTS = {
    "513":    "software platform data management analytics",
    "541511": "software development platform custom application",
    "541512": "computer systems design technology platform",
    "541519": "computer services it solution technology",
    "518210": "data processing hosting cloud platform analytics",
    "541690": "technical consulting analytics data solution",
    "922":    "law enforcement criminal justice public safety",
    "922110": "courts criminal justice case management",
    "922120": "police law enforcement public safety records",
    "922150": "probation parole corrections supervision offender",
    "922190": "public safety justice corrections law enforcement",
    "923":    "corrections supervision justice case management",
}

def score_opportunity(opp: Opportunity) -> Opportunity:
    """
    Score based on capability match. Permissive — surfaces anything that could
    plausibly involve Peregrine's platform. Uses NAICS hints when description
    is empty (common with SAM.gov search API).
    """
    # Build enriched text including NAICS-derived capability hints
    naics_hint = ""
    if opp.naics:
        for prefix, hint in NAICS_CAPABILITY_HINTS.items():
            if opp.naics.startswith(prefix):
                naics_hint = hint
                break
    # Score only against title + description + NAICS hints
    # Agency name intentionally excluded — an agency match alone is not a capability fit
    text = f" {opp.title} {opp.description} {naics_hint} ".lower()  # padded for word-boundary phrase matching
    # Keep agency text separate for display only
    agency_text = opp.agency.lower()
    for excl in HARD_EXCLUSIONS:
        if excl.lower() in text:
            opp.score = -1
            opp.tier = "⛔ Not a Fit"
            opp.score_reasons = [f"Excluded: unrelated work (contains '{excl}')"]
            return opp

    # ── 2. Expired opportunity check ─────────────────────────────────────────
    if is_expired(opp):
        opp.score = -1
        opp.tier = "⛔ Expired"
        opp.score_reasons = [f"Response deadline has passed ({opp.response_date})"]
        return opp

    # ── 3. Capability cluster matching ───────────────────────────────────────
    score = 0
    reasons = []
    clusters_matched = 0
    title_only = opp.title.lower()
    saas_hits = []  # Track SaaS hits separately — only count if core cluster also matched

    for cap_name, cap_points, phrases in CAPABILITY_CLUSTERS:
        # Always check title independently — SAM.gov often has rich titles but empty descriptions
        # A title match alone is always meaningful and should always score
        title_hits = [p for p in phrases if p.lower() in title_only]
        desc_hits  = [p for p in phrases if p.lower() in text]
        # Merge, deduplicate, prefer longer (more specific) phrases
        all_hits = list({p: None for p in (title_hits + desc_hits)}.keys())

        if not all_hits:
            continue

        # Flag if this was a title-only match so we can note it
        title_only_match = bool(title_hits) and not bool(desc_hits)

        # Secure SaaS cluster: defer — only count if a core cluster also matched
        if cap_name.startswith("Secure Government SaaS"):
            saas_hits = all_hits
            continue

        score += cap_points
        clusters_matched += 1
        top_hits = sorted(all_hits, key=len, reverse=True)[:3]
        source_note = " (title match)" if title_only_match else ""
        reasons.append(f"✓ {cap_name}: matched '{top_hits[0]}'{source_note}" +
                      (f" + {len(all_hits)-1} more" if len(all_hits) > 1 else ""))

    # Now add SaaS score — but ONLY if at least one core capability cluster matched
    if saas_hits and clusters_matched >= 1:
        score += 15
        clusters_matched += 1
        top = sorted(saas_hits, key=len, reverse=True)[0]
        reasons.append(f"✓ Secure Govt SaaS context: '{top}' (with core capability match)")

    # ── 4. Penalty signals ───────────────────────────────────────────────────
    for signal, penalty in PENALTY_SIGNALS:
        if signal.lower() in text:
            score += penalty
            reasons.append(f"⚠ Penalty: '{signal}' suggests partial mismatch ({penalty} pts)")

    # ── 5. Assign tier — purely capability-based, no bonuses ────────────────
    # Strong Fit = 2+ clusters matched (40+ pts)
    # Good Fit   = 1 cluster matched  (15-39 pts)
    # Possible   = partial signal      (1-14 pts)
    if score >= 40:
        tier = "🟢 Strong Fit"
    elif score >= 15:
        tier = "🟡 Good Fit"
    elif score > 0:
        tier = "🔵 Possible Fit"
    else:
        tier = "⚪ Low Fit"

    opp.score = max(score, 0)
    opp.tier = tier
    opp.score_reasons = reasons if reasons else [
        "No clear capability match — review manually"
    ]
    return opp

# ---------------------------------------------------------------------------
# SOURCE 1: SAM.gov (all agency-targeted searches in one function)
# Public API key limit: 1,000 calls/day. This function uses ~55 calls total.
# ---------------------------------------------------------------------------

_SAM_RATE_LIMITED = [False]  # global flag — stops all SAM calls on 429
_SAM_RESULTS_CACHE: list = []  # shared cache — DOJ/DHS filter from this

def _sam_search(extra_params: dict, label: str,
                seen_ids: set, results: list) -> bool:
    """One SAM.gov search call. Returns False if rate limited."""
    if _SAM_RATE_LIMITED[0]:
        return False
    try:
        r = requests.get(
            "https://api.sam.gov/opportunities/v2/search",
            params={"api_key": SAM_API_KEY, "active": "Yes",
                    "limit": 100, **extra_params},
            headers=HEADERS, timeout=15,  # 15s max per call
        )
        if r.status_code == 429:
            print(f"[SAM.gov] Rate limit hit — pausing all SAM calls ({label})")
            _SAM_RATE_LIMITED[0] = True
            return False
        if r.status_code != 200:
            return True  # skip bad responses, keep going
        for item in r.json().get("opportunitiesData", []):
            nid = item.get("noticeId") or item.get("id") or ""
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            results.append(score_opportunity(Opportunity(
                title         = item.get("title", "Untitled"),
                notice_id     = nid,
                agency        = (item.get("fullParentPathName")
                                 or item.get("departmentName") or "Unknown"),
                posted_date   = item.get("postedDate", ""),
                response_date = item.get("responseDeadLine", "TBD"),
                description   = (item.get("description") or "")[:2000],
                url           = clean_url(f"https://sam.gov/opp/{nid}/view",
                                          "https://sam.gov/search"),
                opp_type      = item.get("type") or "Notice",
                source        = "SAM.gov",
                naics         = item.get("naicsCode", ""),
            )))
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[SAM.gov] {label}: {e}")
        return True


def fetch_sam_gov() -> list[Opportunity]:
    """
    Comprehensive SAM.gov fetch — covers ALL federal agencies.

    Strategy:
      Pass 1: Paginated ptype sweeps (no agency filter) — catches everything
              posted in last 30 days across all agencies. 2 pages per ptype
              = up to 200 results per notice type.
      Pass 2: Capability title searches across all agencies — 90-day window,
              paginated for high-volume terms. Catches older opps and anything
              that fell outside the ptype page limit.
      Pass 3: Broad keyword sweep for Peregrine-specific terms that wouldn't
              appear in generic ptype sweeps.

    Results are cached for DOJ/DHS/DoD to post-filter at zero extra cost.
    """
    if not SAM_API_KEY:
        print("[SAM.gov] No API key — skipping")
        return []

    results, seen_ids = [], set()
    today   = datetime.utcnow()
    to_date = today.strftime("%m/%d/%Y")
    d30     = (today - timedelta(days=30)).strftime("%m/%d/%Y")
    d90     = (today - timedelta(days=90)).strftime("%m/%d/%Y")

    # ── Pass 1: Paginated ptype sweeps — ALL agencies, last 30 days ───────────
    # 2 pages × 100 results = up to 200 per notice type across every agency
    for ptype, lbl in [
        ("r", "Sources Sought"),
        ("p", "Presolicitation"),
        ("k", "Combined Synopsis"),
        ("s", "Special Notice"),
        ("o", "Solicitation"),
        ("i", "Intent to Bundle"),
    ]:
        if not _sam_search({"ptype": ptype, "postedFrom": d30, "postedTo": to_date},
                           lbl, seen_ids, results, pages=2):
            break

    # ── Pass 2: Capability title searches — ALL agencies, 90-day window ───────
    # Covers opps older than 30 days and anything missed by ptype page cap.
    # High-volume terms paginated to 3 pages (up to 300 results each).
    TITLE_SEARCHES = [
        # Specific compound phrases — low volume, 1 page sufficient
        ("investigative platform",     1),
        ("community supervision",      1),
        ("digital evidence",           1),
        ("federated search",           1),
        ("law enforcement analytics",  1),
        ("public safety platform",     1),
        ("entity resolution",          1),
        ("crime analytics",            1),
        ("offender management",        1),
        ("records management system",  1),
        ("enterprise data",            1),
        ("data environment",           1),
        ("data fabric",                1),
        ("zero trust analytics",       1),
        ("fedramp analytics",          1),
        ("investigative analytics",    1),
        ("intelligence platform",      1),
        ("identity resolution",        1),
        ("record deduplication",       1),
        ("crime gun intelligence",     1),
        ("body camera analytics",      1),
        ("corrections platform",       1),
        ("fusion center",              1),
        ("platform replacement",       1),
        ("computer vision analytics",  1),
        ("surveillance analytics",     1),
        ("data unification",           1),
        ("information sharing platform", 1),
        # High-volume terms — paginate to catch deeper results
        ("data analytics",             3),
        ("data integration",           3),
        ("IT modernization",           2),
        ("artificial intelligence",    3),
        ("machine learning",           2),
        ("platform modernization",     2),
        ("predictive analytics",       2),
        ("data management",            2),
        ("digital transformation",     2),
    ]
    for term, pages in TITLE_SEARCHES:
        if _SAM_RATE_LIMITED[0]:
            break
        if not _sam_search({"title": term, "postedFrom": d90, "postedTo": to_date},
                           f"title={term}", seen_ids, results, pages=pages):
            break

    # Cache for DOJ/DHS/DoD post-filtering — zero extra API calls
    _SAM_RESULTS_CACHE.clear()
    _SAM_RESULTS_CACHE.extend(results)
    print(f"[SAM.gov] {len(results)} total opportunities across all agencies")
    return results
