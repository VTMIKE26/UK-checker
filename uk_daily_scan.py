"""
Peregrine UK Daily Scanner
===========================
Finds UK public procurement opportunities matching Peregrine's capabilities
across all five official UK procurement portals.

Key insight (Procurement Act 2023, in force Feb 2025):
  Find a Tender now covers ALL UK procurement lifecycle — pipeline through
  termination — for England, Wales, and Northern Ireland. Scotland remains
  on Public Contracts Scotland for below-threshold.

Strategy:
  1. FTS OCDS API — filtered by RELEVANT CPV codes only (IT/software/LE)
     This is far more precise than keyword-only searching
  2. FTS keyword searches — for Peregrine-specific terms with hard scoring
  3. Sell2Wales RSS — Welsh public sector (Police Wales, probation, councils)
  4. PCS keyword RSS — Scottish public sector (Police Scotland, SPS, COPFS)
  5. Competitor intelligence — Google News UK per competitor
  6. UK policing/justice news feeds
"""

from __future__ import annotations
import os, re, time, xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_TO         = os.environ.get("EMAIL_TO", "")
EMAIL_FROM       = os.environ.get("EMAIL_FROM", "")

HEADERS = {"User-Agent": "PeregrineUKScanner/2.0 (+peregrine.io)", "Accept": "application/json"}

# ---------------------------------------------------------------------------
# CPV CODE STRATEGY
# ---------------------------------------------------------------------------
# These CPV codes represent IT/software/data services and law enforcement.
# Filtering by CPV is MORE RELIABLE than keyword search because:
#   - Every UK tender must declare a CPV code by law
#   - CPV 722-729 = IT services (always relevant)
#   - CPV 480 = Software packages (always relevant)
#   - CPV 752 = Law enforcement services (always relevant)
#   - CPV 751 = Public administration (potentially relevant)
#   - CPV 730 = R&D services (potentially relevant for AI/data)

# CPV prefixes where we ALWAYS keep the result (IT/software/LE)
ALWAYS_RELEVANT_CPV_PREFIXES = {
    "722", "723", "724", "725", "726", "727", "728", "729",  # IT services
    "480", "481", "482", "483", "484", "485", "486", "487", "488", "489",  # Software
    "752",  # Law enforcement / public security
}

# CPV prefixes where we keep ONLY if also keyword-scored > 0
CONDITIONAL_CPV_PREFIXES = {
    "721",  # IT consultancy
    "730",  # R&D services
    "751",  # Public administration
    "753",  # Compulsory social security
    "792",  # Investigation / security services
    "634",  # Postal/courier (sometimes case file services)
}

CPV_LABELS = {
    "722": "IT services: consulting, software dev, internet",
    "723": "Data processing services",
    "724": "Internet services",
    "725": "Computer-related services",
    "726": "Computer-related services",
    "727": "Computer network services",
    "728": "Computer audit and testing",
    "729": "Miscellaneous computer services",
    "480": "Software packages and information systems",
    "752": "Law enforcement / public security services",
    "721": "IT consultancy services",
    "730": "Research and development services",
    "751": "Administration services",
}

# ---------------------------------------------------------------------------
# TARGET BUYER TYPES
# ---------------------------------------------------------------------------
# We post-score by buyer type — these are Peregrine's actual customer types
# Matching any of these in the buyer name adds a relevance boost

TIER1_BUYERS = [
    # Police forces
    "police", "constabulary", "met police", "metropolitan police",
    "city of london police", "british transport police",
    # Justice / corrections
    "ministry of justice", "hm prison", "hmpps", "national probation",
    "hmps", "youth offending", "youth justice board",
    # National agencies
    "national crime agency", "nca", "serious fraud office",
    "crown prosecution service", "cps",
    "home office", "home department",
    "uk border force", "immigration enforcement",
    # Intelligence
    "national counter terrorism", "nctp",
    "joint terrorism analysis",
]

TIER2_BUYERS = [
    # Central government with data/analytics needs
    "cabinet office", "hmrc", "dwp", "department for work",
    "ministry of defence", "mod", "dstl",
    "department of health", "nhsx", "nhs digital", "nhs england",
    # Devolved policing/justice
    "police scotland", "scottish prison service", "crown office",
    "procurator fiscal", "northern ireland courts",
    "psni", "police service of northern ireland",
    # Local government (LE adjacent)
    "probation", "youth offending team", "safeguarding",
    # CCS / frameworks
    "crown commercial service", "government digital service", "gds",
    "central digital",
]

# ---------------------------------------------------------------------------
# SCORING ENGINE
# ---------------------------------------------------------------------------
CAPABILITY_CLUSTERS = [
    ("Data Integration & Unification", 20, [
        "data integration", "data unification", "data fusion",
        "data harmonisation", "data harmonization", "enterprise data platform",
        "data consolidation", "data normalisation", "data normalization",
        "data pipeline", "data fabric", "data lake", "data warehouse",
        "data mesh", "data analytics", "analytics platform",
        "data management platform", "data solution", "data platform",
        "analytics solution", "business intelligence",
        "enterprise software", "cloud platform",
        "information sharing platform", "master data management",
    ]),
    ("Investigative & Operational Analytics", 20, [
        "investigative analytics", "investigative platform",
        "link analysis", "relationship mapping",
        "situational awareness", "operational intelligence",
        "crime analytics", "crime analysis", "advanced analytics",
        "intelligence platform", "predictive analytics",
        "geospatial analysis", "geospatial intelligence",
        "digital evidence", "evidence review platform",
        "evidence analytics", "evidence management platform",
        "digital forensics platform", "investigative data platform",
        "body worn video analytics",
    ]),
    ("Federated & Enterprise Search", 20, [
        "federated search", "enterprise search", "cross-system search",
        "unified search", "cross-database search",
        "multi-source search", "search federation",
        "information retrieval",
    ]),
    ("Entity Resolution & Record Intelligence", 20, [
        "entity resolution", "record deduplication", "record linkage",
        "duplicate records", "identity resolution", "identity matching",
        "record matching", "data deduplication", "entity matching",
        "knowledge graph", "person resolution", "fuzzy matching",
        "probabilistic matching", "golden record", "data quality",
    ]),
    ("Secure Government SaaS", 15, [
        "cyber essentials", "official sensitive", "jsig", "iso 27001",
        "cloud security", "secure cloud", "government cloud",
        "g-cloud", "gcloud", "zero trust",
        "identity and access management", "audit logging",
        "il2", "il3", "il4", "official-sensitive",
        "dsp toolkit",
    ]),
    ("Public Safety & Law Enforcement", 20, [
        "law enforcement platform", "law enforcement software",
        "law enforcement analytics", "law enforcement data",
        "law enforcement technology", "police data", "police analytics",
        "policing platform", "policing software", "policing analytics",
        "public safety platform", "public safety software",
        "public safety technology", "public safety data",
        "public safety analytics", "public safety system",
        "records management system", "crime recording system",
        "custody suite", "custody management",
        "computer aided dispatch", "cad system",
        "serious and organised crime", "intelligence management",
        "national intelligence model",
        "fusion centre", "fusion center",
        "digital forensics", "digital investigation",
        "body worn video", "body worn camera", "bwv",
        "automatic number plate recognition", "anpr",
        "stop and search data", "use of force data",
        "police national database", "pnd", "pnc",
        "national police systems", "connect system",
    ]),
    ("Corrections & Community Supervision", 20, [
        "community supervision", "probation", "parole",
        "offender management", "prison management", "prisoner management",
        "case management system", "rehabilitation technology",
        "hmpps", "hmps", "noms", "her majesty's prison",
        "youth offending", "youth justice",
        "electronic monitoring", "electronic tagging",
        "curfew monitoring", "offender data",
        "community payback", "unpaid work",
        "reoffending", "desistance",
    ]),
    ("Platform Modernisation & Replacement", 20, [
        "platform replacement", "incumbent replacement",
        "platform consolidation", "legacy platform",
        "legacy system", "legacy modernisation", "legacy modernization",
        "platform modernisation", "platform modernization",
        "it modernisation", "it modernization",
        "digital transformation", "cloud migration",
        "software modernisation", "application modernisation",
        "system replacement programme",
        "palantir", "niche", "xhibit",
    ]),
    ("AI & Machine Learning", 22, [
        "artificial intelligence", "machine learning",
        "ai/ml", "ai platform", "ai solution", "ai system",
        " generative ai", "generative ai ",
        "large language model", "llm",
        "natural language processing", "nlp",
        "computer vision", "predictive model",
        "decision support system", "automated analysis",
        "ai-powered", "ai-driven",
        "responsible ai", "explainable ai",
        "ai governance", "ai analytics",
    ]),
]

HARD_EXCLUSIONS = [
    # Physical facilities & construction
    "fire suppression", "fire alarm system", "hvac", "plumbing",
    "electrical installation", "roof replacement", "flooring contract",
    "window replacement", "lift maintenance", "elevator maintenance",
    "lighting installation", "cctv installation", "camera installation",
    "grounds maintenance", "grass cutting", "hedge cutting",
    "horticulture", "arboriculture", "tree surgery",
    "landscaping", "grounds keeping", "cleaning contract",
    "waste management", "recycling contract",
    # Physical goods
    "uniform supply", "workwear", "stationery supply",
    "office furniture", "catering services", "food supply",
    "medical supplies", "pharmaceutical", "laundry services",
    "body armour", "taser", "firearms", "ammunition",
    "vehicle purchase", "fleet management",
    "radio equipment", "handheld devices procurement",
    # Construction
    "construction works", "refurbishment works", "building works",
    "estates management", "facilities management", "janitorial",
    # Network/telecom (infrastructure, not platforms)
    "network cabling", "structured cabling",
    "fibre optic installation", "wide area network service",
    "mobile phone contract", "cellular service contract",
    "telephony system", "pbx system", "voip hardware",
    # Hardware maintenance (not software)
    "hardware maintenance contract", "server hardware support",
    "printer maintenance", "copier maintenance", "mfd maintenance",
    "planned preventive maintenance", "ppm contract",
    "reactive maintenance contract",
    # Licence renewals (not new platforms)
    "microsoft licence renewal", "oracle licence renewal",
    "software licence renewal", "saas licence renewal",
    # Staffing only
    "staffing agency", "temporary staffing",
    "security guard services", "door supervision",
    "close protection services",
    # Treatment / social (not LE tech)
    "drug treatment programme", "alcohol treatment",
    "mental health treatment", "substance misuse services",
    "domestic abuse refuge", "homeless shelter",
    "food bank", "welfare benefits",
    # Training only
    "firearms training", "first aid training",
    "physical training contract", "driver training",
    # Military hardware (not analytics)
    "crypto modernisation hardware", "avionics", "missile",
    "munitions", "weapons system", "armoured vehicle",
    "naval vessel", "aircraft maintenance contract",
    # Specific non-relevant service types
    "translation services", "interpretation services",
    "legal representation", "financial audit",
    "accountancy services", "actuarial services",
    "insurance services", "printing services",
    "mail services", "courier services",
]

TIER_STRONG, TIER_GOOD = 40, 15


@dataclass
class Opportunity:
    title:         str
    notice_id:     str
    buyer:         str
    buyer_type:    str = ""   # tier1 / tier2 / other
    posted_date:   str = ""
    deadline:      str = "TBD"
    description:   str = ""
    url:           str = ""
    opp_type:      str = ""
    source:        str = ""
    cpv_code:      str = ""
    cpv_label:     str = ""
    value_gbp:     float = 0.0
    score:         int = 0
    tier:          str = ""
    score_reasons: list = field(default_factory=list)


def _classify_buyer(buyer_name: str) -> str:
    b = buyer_name.lower()
    if any(t in b for t in TIER1_BUYERS):
        return "tier1"
    if any(t in b for t in TIER2_BUYERS):
        return "tier2"
    return "other"


def score_opportunity(opp: Opportunity) -> Opportunity:
    text = f" {opp.title} {opp.description} {opp.cpv_label} ".lower()

    # Hard exclusions — instant disqualify
    for excl in HARD_EXCLUSIONS:
        if excl in text:
            opp.tier = "⛔ Not a Fit"
            opp.score = 0
            return opp

    total, reasons = 0, []
    for cluster_name, pts, phrases in CAPABILITY_CLUSTERS:
        matched = next((p for p in phrases if p in text), None)
        if matched:
            total += pts
            reasons.append(f"✓ {cluster_name}: matched '{matched}'")

    # Buyer type bonus — Tier 1 buyers get a lift regardless of base score
    buyer_type = _classify_buyer(opp.buyer)
    opp.buyer_type = buyer_type
    if buyer_type == "tier1":
        total += 10
        reasons.append("✓ Priority buyer: law enforcement / justice / policing")
    elif buyer_type == "tier2":
        total += 5
        reasons.append("✓ Relevant buyer: government / public safety adjacent")

    opp.score = total
    opp.score_reasons = reasons
    opp.tier = ("🟢 Strong Fit" if total >= TIER_STRONG
                else "🟡 Good Fit" if total >= TIER_GOOD
                else "🔵 Possible Fit" if total > 0
                else "⚪ Low Fit")
    return opp


def parse_deadline(date_str: str) -> Optional[datetime]:
    if not date_str or date_str == "TBD":
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt)
        except Exception:
            pass
    return None


def is_expired(opp: Opportunity) -> bool:
    dt = parse_deadline(opp.deadline)
    return bool(dt and dt < datetime.utcnow() - timedelta(days=1))


def clean_url(url: str) -> str:
    url = (url or "").strip()
    return ("https://" + url) if url and not url.startswith("http") else url


def _extract_fts_opp(rel: dict, source_label: str = "Find a Tender") -> Optional[Opportunity]:
    """Parse one FTS OCDS release into an Opportunity. Returns None if invalid."""
    tender   = rel.get("tender") or {}
    uid      = (rel.get("id") or rel.get("ocid") or "").strip()
    title    = (tender.get("title") or "").strip()
    status   = tender.get("status", "")
    if not uid or not title or status in ("cancelled", "withdrawn", "complete"):
        return None

    buyer_name = (rel.get("buyer") or {}).get("name", "Unknown")
    for p in rel.get("parties") or []:
        if "buyer" in (p.get("roles") or []):
            buyer_name = p.get("name", buyer_name)
            break

    cpv_code  = (tender.get("classification") or {}).get("id", "")
    cpv_desc  = (tender.get("classification") or {}).get("description", "")
    cpv_label = CPV_LABELS.get(cpv_code[:3], cpv_desc)
    deadline  = ((tender.get("tenderPeriod") or {}).get("endDate") or "TBD")
    value     = float(((tender.get("value") or {}).get("amount") or 0))
    posted    = (rel.get("date") or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]
    desc      = (tender.get("description") or "")[:2000]

    notice_id_clean = uid.replace("/", "-")
    url = clean_url(f"https://www.find-tender.service.gov.uk/Notice/{notice_id_clean}")

    return Opportunity(
        title=title, notice_id=uid, buyer=buyer_name,
        posted_date=posted, deadline=deadline,
        description=f"{desc} {cpv_desc}"[:2000],
        url=url, opp_type=(rel.get("tag") or ["tender"])[0],
        source=source_label, cpv_code=cpv_code, cpv_label=cpv_label,
        value_gbp=value,
    )


# ---------------------------------------------------------------------------
# SOURCE 1: FTS — CPV-FILTERED (most precise)
# ---------------------------------------------------------------------------
FTS_API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"

def fetch_fts_by_cpv(days_back: int = 90) -> list:
    """
    Fetch FTS tenders filtered by relevant CPV code prefixes.
    Paginates fully through all tenders in the window.
    FTS returns ~500-2000 tenders/day across all categories.
    We keep only IT/software/LE CPV codes (722-729, 480-489, 752).
    """
    results, seen = [], set()
    today   = datetime.utcnow()
    from_dt = (today - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
    to_dt   = today.strftime("%Y-%m-%dT23:59:59")

    cursor     = None
    pages      = 0
    total_seen = 0
    max_pages  = 50  # up to 5000 tenders

    while pages < max_pages:
        params = {"updatedFrom": from_dt, "updatedTo": to_dt, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(FTS_API, params=params,
                             headers={**HEADERS, "Accept": "application/json"}, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 30))
                print(f"[FTS/CPV] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"[FTS/CPV] HTTP {r.status_code} on page {pages+1}")
                break
            data     = r.json()
            releases = data.get("releases", [])
            if not releases:
                break
            total_seen += len(releases)
            for rel in releases:
                opp = _extract_fts_opp(rel, "Find a Tender")
                if not opp or opp.notice_id in seen:
                    continue
                cpv_prefix = opp.cpv_code[:3] if opp.cpv_code else ""
                # ONLY keep IT/software/LE CPV codes
                if (cpv_prefix not in ALWAYS_RELEVANT_CPV_PREFIXES and
                        cpv_prefix not in CONDITIONAL_CPV_PREFIXES):
                    continue
                seen.add(opp.notice_id)
                results.append(score_opportunity(opp))
            cursor = data.get("cursor")
            pages += 1
            if not cursor or len(releases) < 100:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"[FTS/CPV] page {pages}: {e}")
            break

    # Keep scored > 0 OR always-relevant CPV (even if scored 0, shows in Low Fit)
    relevant = [o for o in results
                if o.tier != "⛔ Not a Fit"
                and (o.score > 0 or o.cpv_code[:3] in ALWAYS_RELEVANT_CPV_PREFIXES)]

    print(f"[FTS/CPV] {total_seen} total tenders scanned → {len(results)} CPV-matched → {len(relevant)} relevant")
    return relevant


# ---------------------------------------------------------------------------
# SOURCE 2: FTS — KEYWORD SEARCH (Peregrine-specific terms)
# ---------------------------------------------------------------------------
def fetch_fts_by_keyword(days_back: int = 90) -> list:
    """
    FTS keyword searches via the web search endpoint.
    Uses /Search?keyword=TERM which is the same as the FTS website search.
    Returns OCDS releases for matching notices.
    Also tries the OCDS API with keyword param as fallback.
    """
    results, seen = [], set()
    today   = datetime.utcnow()
    from_dt = (today - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
    to_dt   = today.strftime("%Y-%m-%dT23:59:59")

    # Highly specific Peregrine terms — each should return <50 results
    TERMS = [
        "data analytics policing",
        "law enforcement data platform",
        "investigative analytics",
        "crime analytics platform",
        "police data platform",
        "offender management system",
        "community supervision technology",
        "custody management system",
        "digital evidence platform",
        "body worn video analytics",
        "intelligence platform police",
        "records management police",
        "predictive policing analytics",
        "artificial intelligence policing",
        "machine learning criminal justice",
        "data integration law enforcement",
        "entity resolution identity",
        "federated search police",
    ]

    for term in TERMS:
        try:
            # Try OCDS API with keyword param
            r = requests.get(
                FTS_API,
                params={"updatedFrom": from_dt, "updatedTo": to_dt,
                        "limit": 100, "keyword": term},
                headers={**HEADERS, "Accept": "application/json"}, timeout=20,
            )
            if r.status_code == 200:
                for rel in r.json().get("releases", []):
                    opp = _extract_fts_opp(rel, "Find a Tender")
                    if not opp or opp.notice_id in seen:
                        continue
                    seen.add(opp.notice_id)
                    scored = score_opportunity(opp)
                    if scored.tier != "⛔ Not a Fit" and scored.score > 0:
                        results.append(scored)
            time.sleep(0.3)
        except Exception as e:
            print(f"[FTS/KW] '{term}': {e}")

    print(f"[FTS/Keyword] {len(results)} scored relevant")
    return results



# ---------------------------------------------------------------------------
# SOURCE 3: SELL2WALES — Welsh public sector RSS
# ---------------------------------------------------------------------------
S2W_RSS = "https://www.sell2wales.gov.wales/Search/Search_Rss.aspx"

def fetch_sell2wales() -> list:
    """
    Sell2Wales — official procurement portal for Welsh public sector.
    Covers Police Wales, Welsh Government, Welsh NHS, councils.
    Uses the public keyword RSS feed.
    """
    results, seen = [], set()
    today = datetime.utcnow()

    TERMS = [
        "data analytics", "artificial intelligence", "police",
        "digital evidence", "community supervision", "offender management",
        "records management", "intelligence platform", "machine learning",
        "digital transformation", "investigative", "criminal justice",
    ]
    for term in TERMS:
        try:
            r = requests.get(S2W_RSS, params={"term": term},
                             headers={"User-Agent": HEADERS["User-Agent"],
                                      "Accept": "application/rss+xml"},
                             timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:10]:
                guid  = (item.find("guid") or item.find("link"))
                title_el = item.find("title")
                link_el  = item.find("link")
                desc_el  = item.find("description")
                date_el  = item.find("pubDate")
                title  = (title_el.text or "").strip() if title_el is not None else ""
                desc   = unescape(re.sub(r"<[^>]+>","", (desc_el.text or ""))).strip() if desc_el is not None else ""
                url_   = (link_el.text or "").strip() if link_el is not None else ""
                date_  = (date_el.text or "").strip() if date_el is not None else ""
                uid    = (guid.text if guid is not None else url_) or url_
                if not title or uid in seen:
                    continue
                seen.add(uid)
                opp = Opportunity(
                    title=title, notice_id=f"S2W-{hash(uid) % 10**9}",
                    buyer="Welsh Public Body", posted_date=date_[:10],
                    deadline="TBD", description=desc,
                    url=clean_url(url_), opp_type="Welsh Tender",
                    source="Sell2Wales",
                )
                results.append(score_opportunity(opp))
            time.sleep(0.2)
        except Exception as e:
            print(f"[Sell2Wales] '{term}': {e}")

    relevant = [o for o in results if o.score > 0 and o.tier != "⛔ Not a Fit"]
    print(f"[Sell2Wales] {len(results)} fetched → {len(relevant)} relevant")
    return relevant


# ---------------------------------------------------------------------------
# SOURCE 4: PUBLIC CONTRACTS SCOTLAND — keyword RSS
# ---------------------------------------------------------------------------
PCS_RSS = "https://www.publiccontractsscotland.gov.uk/search/Search_Rss.aspx"

def fetch_public_contracts_scotland() -> list:
    """
    Public Contracts Scotland — covers Police Scotland, Scottish Prison
    Service, COPFS, Scottish Government, 32 councils, NHS Scotland.
    """
    results, seen = [], set()
    today = datetime.utcnow()

    TERMS = [
        "data analytics", "artificial intelligence", "police",
        "digital evidence", "community supervision", "offender management",
        "records management", "intelligence platform", "machine learning",
        "criminal justice", "investigative platform",
    ]
    for term in TERMS:
        try:
            r = requests.get(PCS_RSS, params={"term": term},
                             headers={"User-Agent": HEADERS["User-Agent"],
                                      "Accept": "application/rss+xml"},
                             timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:10]:
                guid_el  = item.find("guid")
                title_el = item.find("title")
                link_el  = item.find("link")
                desc_el  = item.find("description")
                date_el  = item.find("pubDate")
                title = (title_el.text or "").strip() if title_el is not None else ""
                desc  = unescape(re.sub(r"<[^>]+>","", (desc_el.text or ""))).strip() if desc_el is not None else ""
                url_  = (link_el.text or "").strip() if link_el is not None else ""
                uid   = (guid_el.text if guid_el is not None else url_) or url_
                date_ = (date_el.text or "").strip() if date_el is not None else ""
                if not title or uid in seen:
                    continue
                seen.add(uid)
                # Extract buyer from description (PCS puts it in description)
                buyer = desc[:80] if desc else "Scottish Public Body"
                opp = Opportunity(
                    title=title, notice_id=f"PCS-{hash(uid) % 10**9}",
                    buyer=buyer, posted_date=date_[:10],
                    deadline="TBD", description=desc,
                    url=clean_url(url_), opp_type="Scottish Tender",
                    source="Public Contracts Scotland",
                )
                results.append(score_opportunity(opp))
            time.sleep(0.2)
        except Exception as e:
            print(f"[PCS] '{term}': {e}")

    relevant = [o for o in results if o.score > 0 and o.tier != "⛔ Not a Fit"]
    print(f"[Public Contracts Scotland] {len(results)} fetched → {len(relevant)} relevant")
    return relevant


# ---------------------------------------------------------------------------
# COMPETITOR INTELLIGENCE
# ---------------------------------------------------------------------------
UK_COMPETITORS = [
    ("Palantir UK",         "Palantir+UK+government+police+data"),
    ("Axon UK",             "Axon+Enterprise+UK+police+technology"),
    ("Motorola Solutions",  "Motorola+Solutions+UK+police+public+safety"),
    ("IBM i2",              "IBM+i2+UK+intelligence+analytics"),
    ("Civica",              "Civica+UK+law+enforcement+police+software"),
    ("NEC UK",              "NEC+UK+police+facial+recognition+biometrics"),
    ("Hexagon Safety",      "Hexagon+UK+police+CAD+records+management"),
    ("Capita Justice",      "Capita+UK+justice+probation+data"),
    ("Sopra Steria",        "Sopra+Steria+UK+police+justice+digital"),
    ("CGI UK",              "CGI+UK+police+criminal+justice+technology"),
    ("BAE Systems Detica",  "BAE+Detica+UK+police+intelligence+analytics"),
    ("Unison / Fujitsu",    "Fujitsu+UK+police+national+systems"),
]

def fetch_uk_competitor_intel() -> list:
    items, seen = [], set()
    for comp_name, query in UK_COMPETITORS:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"
        try:
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; PeregrineUKScanner/2.0)",
                "Accept": "application/rss+xml",
            }, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            count = 0
            for item in root.findall(".//item"):
                if count >= 2:
                    break
                t_el = item.find("title");  l_el = item.find("link")
                d_el = item.find("description"); p_el = item.find("pubDate")
                title = (t_el.text or "").strip() if t_el is not None else ""
                desc  = unescape(re.sub(r"<[^>]+>","", (d_el.text or ""))).strip() if d_el is not None else ""
                url_  = (l_el.text or "").strip() if l_el is not None else ""
                date_ = (p_el.text or "").strip() if p_el is not None else ""
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({"competitor": comp_name, "title": title,
                              "url": clean_url(url_), "source": "Google News (UK)",
                              "date": date_[:16], "summary": desc[:300]})
                count += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"[CompIntel] {comp_name}: {e}")
    print(f"[UK Competitor Intel] {len(items)} signals")
    return items


# ---------------------------------------------------------------------------
# UK INDUSTRY NEWS
# ---------------------------------------------------------------------------
UK_NEWS_FEEDS = [
    {"url": "https://www.publictechnology.net/feed/",             "source": "PublicTechnology"},
    {"url": "https://www.policeoracle.com/rss/news.xml",          "source": "PoliceOracle"},
    {"url": "https://www.ukauthority.com/feed/",                  "source": "UKAuthority"},
    {"url": "https://www.gov.uk/search/news-and-communications.atom?keywords=policing+data+analytics", "source": "GOV.UK Policing"},
    {"url": "https://www.gov.uk/search/news-and-communications.atom?keywords=criminal+justice+technology", "source": "GOV.UK Justice"},
    {"url": "https://www.computerweekly.com/rss/Latest-IT-news.xml", "source": "Computer Weekly"},
    {"url": "https://techscoop.co.uk/feed/",                      "source": "TechScoop"},
]

UK_KW = [
    "law enforcement", "policing", "public safety", "data analytics",
    "artificial intelligence", "machine learning", "criminal justice",
    "home office", "ministry of justice", "national police",
    "probation", "prison", "hmpps", "digital transformation",
    "records management", "digital evidence", "predictive",
    "intelligence platform", "surveillance data",
]

def fetch_uk_industry_news() -> list:
    news, seen = [], set()
    for feed in UK_NEWS_FEEDS:
        try:
            r = requests.get(feed["url"], headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml",
            }, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            NS = "http://www.w3.org/2005/Atom"
            items = root.findall(".//item") or root.findall(f".//{{{NS}}}entry")
            for item in items[:20]:
                t_el = item.find("title") or item.find(f"{{{NS}}}title")
                l_el = item.find("link")  or item.find(f"{{{NS}}}link")
                d_el = item.find("description") or item.find(f"{{{NS}}}summary")
                p_el = item.find("pubDate") or item.find(f"{{{NS}}}published")
                title = (t_el.text or "").strip() if t_el is not None else ""
                desc  = unescape(re.sub(r"<[^>]+>","", (d_el.text or ""))).strip() if d_el is not None else ""
                url_  = (l_el.get("href", l_el.text or "") if l_el is not None else "").strip()
                date_ = (p_el.text or "").strip() if p_el is not None else ""
                if not title or title in seen:
                    continue
                if not any(kw in f"{title} {desc}".lower() for kw in UK_KW):
                    continue
                seen.add(title)
                news.append({"title": title, "url": clean_url(url_),
                             "source": feed["source"], "date": date_[:16],
                             "summary": desc[:250]})
            time.sleep(0.2)
        except Exception as e:
            print(f"[UKNews] {feed['source']}: {e}")
    print(f"[UK Industry News] {len(news)} articles")
    return news[:15]


# ---------------------------------------------------------------------------
# DEDUP & RANK
# ---------------------------------------------------------------------------
def deduplicate_and_rank(opps: list) -> list:
    seen, out = set(), []
    for o in sorted(opps, key=lambda x: x.score, reverse=True):
        if is_expired(o):
            continue
        key = o.notice_id or o.title[:60].lower()
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def _fmt_value(val: float) -> str:
    if val <= 0:    return ""
    if val >= 1e6:  return f" · £{val/1e6:.1f}m"
    if val >= 1000: return f" · £{val/1000:.0f}k"
    return f" · £{val:,.0f}"


# ---------------------------------------------------------------------------
# EMAIL RENDERING
# ---------------------------------------------------------------------------
def build_opps_section(title: str, opps: list) -> str:
    if not opps:
        return ""
    rows = ""
    for o in opps[:20]:
        link = (f'<a href="{o.url}" style="font-weight:700;font-size:14px;color:#003078;text-decoration:none;">{o.title[:120]}</a>'
                if o.url else f'<span style="font-weight:700;font-size:14px;color:#111;">{o.title[:120]}</span>')
        reasons_html = ""
        if o.score_reasons:
            bullets = "".join(f"<li>{r}</li>" for r in o.score_reasons[:4])
            reasons_html = (
                '<div style="margin-top:8px;padding:6px 10px;background:#f0f4ff;'
                'border-left:3px solid #003078;border-radius:0 4px 4px 0;">'
                '<div style="font-size:11px;font-weight:700;color:#003078;margin-bottom:3px;'
                'text-transform:uppercase;letter-spacing:0.5px;">Why It Fits</div>'
                f'<ul style="margin:0;padding-left:16px;font-size:12px;color:#444;line-height:1.6;">{bullets}</ul>'
                '</div>'
            )
        deadline_html = ""
        if o.deadline and o.deadline != "TBD":
            dt = parse_deadline(o.deadline)
            if dt:
                days = (dt - datetime.utcnow()).days
                if 0 <= days <= 7:
                    deadline_html = f' <span style="background:#d4351c;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;font-weight:600;">Due in {days}d</span>'
                elif 0 <= days <= 30:
                    deadline_html = f' <span style="background:#f47738;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">Due in {days}d</span>'
        buyer_badge = ""
        if o.buyer_type == "tier1":
            buyer_badge = ' <span style="background:#003078;color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;">🎯 Priority</span>'
        elif o.buyer_type == "tier2":
            buyer_badge = ' <span style="background:#505a5f;color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;">Relevant</span>'
        rows += (
            '<div style="border:1px solid #e0e0e0;border-radius:6px;padding:12px;margin-bottom:10px;background:#fff;">'
            f'<div style="margin-bottom:5px;">{link}{deadline_html}</div>'
            f'<div style="font-size:12px;color:#555;">🏛 {o.buyer[:80]}{buyer_badge} &nbsp;·&nbsp; 📬 {o.posted_date[:10]}{_fmt_value(o.value_gbp)}</div>'
            f'<div style="font-size:11px;color:#999;margin-top:2px;">Source: {o.source} &nbsp;·&nbsp; Score: {o.score}pts'
            + (f' &nbsp;·&nbsp; CPV: {o.cpv_code} ({o.cpv_label[:30]})' if o.cpv_code else "")
            + f' &nbsp;·&nbsp; <a href="{o.url}" style="color:#003078;">View</a></div>'
            f'{reasons_html}</div>'
        )
    return (f'<div style="margin:20px 0 6px">'
            f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">{title} ({len(opps)})</h2>'
            f'{rows}</div>')


def build_competitor_section(intel: list) -> str:
    if not intel:
        return ""
    from collections import defaultdict
    grouped = defaultdict(list)
    for item in intel:
        grouped[item["competitor"]].append(item)
    rows = ""
    for comp in sorted(grouped):
        stories = grouped[comp][:2]
        sh = ""
        for s in stories:
            link = (f'<a href="{s["url"]}" style="color:#003078;text-decoration:none;font-weight:600;">{s["title"][:90]}</a>'
                    if s.get("url") else f'<span style="font-weight:600;">{s["title"][:90]}</span>')
            ns = (f'<div style="font-size:12px;color:#555;margin-top:2px;">{s.get("summary","")[:200]}</div>') if s.get("summary") else ""
            sh += (f'<div style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f0f0f0;">'
                   f'<div style="font-size:13px;">{link}</div>'
                   f'<div style="font-size:11px;color:#888;margin-top:2px;">{s["source"]} &middot; {s["date"][:10]}</div>'
                   f'{ns}</div>')
        rows += (f'<div style="margin-bottom:14px;">'
                 f'<div style="font-weight:700;font-size:12px;color:#555;margin-bottom:5px;text-transform:uppercase;letter-spacing:0.5px;">⚔️ {comp}</div>'
                 f'{sh}</div>')
    return (f'<div style="margin:20px 0 6px">'
            f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">🔎 UK Competitor Intelligence ({len(intel)} signals)</h2>'
            f'<p style="font-size:12px;color:#888;margin:0 0 12px;">Monitoring: {", ".join(c[0] for c in UK_COMPETITORS)}</p>'
            f'{rows}</div>')


def build_news_section(news: list) -> str:
    if not news:
        return ""
    rows = ""
    for item in news[:12]:
        link = (f'<a href="{item["url"]}" style="color:#003078;text-decoration:none;font-weight:600;">{item["title"][:100]}</a>'
                if item.get("url") else f'<span style="font-weight:600;">{item["title"][:100]}</span>')
        ns = (f'<div style="font-size:12px;color:#555;margin-top:2px;">{item.get("summary","")[:200]}</div>') if item.get("summary") else ""
        rows += (f'<div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #f0f0f0;">'
                 f'<div style="font-size:13px;">{link}</div>'
                 f'<div style="font-size:11px;color:#888;margin-top:2px;">{item["source"]} &middot; {item["date"][:10]}</div>'
                 f'{ns}</div>')
    return (f'<div style="margin:20px 0 6px">'
            f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">📰 UK Industry News ({len(news)})</h2>'
            f'{rows}</div>')


def _possible_fits(opps: list, shown: set) -> list:
    def _k(o): return (o.notice_id or o.title[:60].lower()).strip()
    unseen = [o for o in opps if _k(o) not in shown and o.tier != "⛔ Not a Fit"]
    poss   = [o for o in unseen if "Possible" in o.tier]
    if poss:
        return poss
    return sorted([o for o in unseen if o.buyer_type in ("tier1","tier2")],
                  key=lambda x: x.score, reverse=True)[:8]


def build_html_email(opps: list, run_date: str, source_counts: dict,
                     competitor_items: list, news_items: list) -> str:
    def _k(o): return (o.notice_id or o.title[:60].lower()).strip()
    def _dedup(lst):
        seen, out = set(), []
        for o in lst:
            k = _k(o)
            if k not in seen: seen.add(k); out.append(o)
        return out
    shown = set()
    strong = _dedup([o for o in opps if "Strong" in o.tier]); shown.update(_k(o) for o in strong)
    good   = _dedup([o for o in opps if "Good"   in o.tier and _k(o) not in shown]); shown.update(_k(o) for o in good)
    poss   = _dedup([o for o in opps if "Possible" in o.tier and _k(o) not in shown]); shown.update(_k(o) for o in poss)
    low    = _dedup([o for o in opps if o.tier == "⚪ Low Fit" and o.score > 0 and _k(o) not in shown])

    sc_rows = "".join(
        f'<tr><td style="padding:3px 10px;color:#555;font-size:12px;">{k}</td>'
        f'<td style="padding:3px 10px;font-weight:700;font-size:12px;">{v}</td></tr>'
        for k, v in sorted(source_counts.items())
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#f0f2f5;margin:0;padding:0}}
.wrap{{max-width:720px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden}}
.header{{background:#003078;padding:24px 28px;color:#fff}}
.content{{padding:20px 28px}}
</style></head><body>
<div class="wrap">
<div class="header">
  <div style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">&#x1F1EC;&#x1F1E7; Peregrine UK Daily Scanner</div>
  <div style="font-size:13px;opacity:0.8;margin-top:3px;">{run_date}</div>
  <div style="margin-top:12px;display:flex;gap:14px;flex-wrap:wrap;">
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">&#x1F7E2; {len(strong)} Strong</span>
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">&#x1F7E1; {len(good)} Good</span>
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">&#x1F535; {len(poss)} Possible</span>
  </div>
</div>
<div class="content">
  <details style="margin-bottom:16px;border:1px solid #eee;border-radius:6px;padding:8px 12px;">
    <summary style="font-size:12px;color:#888;cursor:pointer;">Sources searched today</summary>
    <table style="margin-top:8px;border-collapse:collapse;">{sc_rows}</table>
  </details>
  {build_opps_section("&#x1F7E2; Strong Fit &#x2014; Act Now", strong)}
  {build_opps_section("&#x1F7E1; Good Fit &#x2014; Review Today", good)}
  {build_opps_section("&#x1F535; Possible Fit &#x2014; Review These", _possible_fits(opps, shown))}
  {build_opps_section("&#x26AA; Low Fit &#x2014; Any Match", low[:10])}
  {build_competitor_section(competitor_items)}
  {build_news_section(news_items)}
</div>
</div></body></html>"""


def send_email(html: str, subject: str):
    print(f"[Email] To: {EMAIL_TO or 'NOT SET'} | From: {EMAIL_FROM or 'NOT SET'} | Key: {'SET' if SENDGRID_API_KEY else 'NOT SET'}")
    if not all([SENDGRID_API_KEY, EMAIL_TO, EMAIL_FROM]):
        print("[Email] SKIPPED — missing config")
        return
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json={"personalizations": [{"to": [{"email": EMAIL_TO}]}],
                  "from": {"email": EMAIL_FROM, "name": "Peregrine UK Scanner"},
                  "subject": subject,
                  "content": [{"type": "text/html", "value": html}]},
            timeout=30,
        )
        print(f"[Email] {'OK (HTTP ' + str(r.status_code) + ')' if r.status_code in (200,202) else 'FAILED: ' + str(r.status_code) + ' ' + r.text[:200]}")
    except Exception as e:
        print(f"[Email] Error: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    today    = datetime.utcnow()
    run_date = today.strftime("%d %B %Y")
    sep = "=" * 60
    print(f"\n{sep}\n  Peregrine UK Daily Scanner -- {run_date}\n{sep}")
    print(f"[Config] SENDGRID_API_KEY: {'SET' if SENDGRID_API_KEY else 'NOT SET'}")
    print(f"[Config] EMAIL_TO: {EMAIL_TO}")

    source_counts, all_opps = {}, []

    opp_sources = [
        ("FTS / CPV Filter",           lambda: fetch_fts_by_cpv(days_back=60)),
        ("FTS / Keyword Search",       lambda: fetch_fts_by_keyword(days_back=90)),
        ("Sell2Wales",                 fetch_sell2wales),
        ("Public Contracts Scotland",  fetch_public_contracts_scotland),
    ]
    for label, fn in opp_sources:
        print(f"\n[{label}] Fetching...")
        try:
            batch = fn()
            source_counts[label] = len(batch)
            all_opps.extend(batch)
        except Exception as e:
            print(f"[{label}] FAILED: {e}")
            source_counts[label] = 0

    print(f"\n[Scoring] Deduplicating {len(all_opps)} raw results...")
    ranked = deduplicate_and_rank(all_opps)
    n_strong   = sum(1 for o in ranked if "Strong" in o.tier)
    n_good     = sum(1 for o in ranked if "Good" in o.tier)
    n_possible = sum(1 for o in ranked if "Possible" in o.tier)
    print(f"[Tiers] Strong:{n_strong}  Good:{n_good}  Possible:{n_possible}")

    print("\n[UK Competitor Intel] Fetching...")
    try:
        competitor_items = fetch_uk_competitor_intel()
        source_counts["Competitor Intel"] = len(competitor_items)
    except Exception as e:
        print(f"[Competitor Intel] FAILED: {e}")
        competitor_items = []

    print("\n[UK Industry News] Fetching...")
    try:
        news_items = fetch_uk_industry_news()
        source_counts["Industry News"] = len(news_items)
    except Exception as e:
        print(f"[Industry News] FAILED: {e}")
        news_items = []

    if n_strong == 0 and n_good == 0:
        subject = f"Peregrine UK Scanner | No Strong Matches | {today.strftime('%d %b')}"
    elif n_strong >= 1:
        subject = f"Peregrine UK Scanner | {n_strong} Strong - {n_good} Good - {n_possible} Possible | {today.strftime('%d %b')}"
    else:
        subject = f"Peregrine UK Scanner | {n_good} Good - {n_possible} Possible | {today.strftime('%d %b')}"

    html = build_html_email(ranked, run_date, source_counts, competitor_items, news_items)
    print(f"[Email] HTML: {len(html):,} chars | Subject: {subject}")
    send_email(html, subject)

    fname = f"uk_digest_{today.strftime('%Y%m%d')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[Done] Saved: {fname}")


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception as e:
        print(f"[FATAL] {type(e).__name__}: {e}")
        traceback.print_exc()
        raise
