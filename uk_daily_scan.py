"""
Peregrine UK Daily Federal Scanner
===================================
Searches UK public procurement for opportunities matching Peregrine's
9 capability clusters. Sources:
  - Find a Tender Service (FTS) OCDS API — no key required
  - Contracts Finder API (below-threshold, England) — no key required
  - UK Government news / policy RSS feeds
  - Competitor intelligence via Google News (UK edition)

Delivers a ranked HTML digest via SendGrid email.
"""

from __future__ import annotations
import os
import re
import time
import json
import xml.etree.ElementTree as ET
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

HEADERS = {
    "User-Agent": "PeregrineUKScanner/1.0",
    "Accept":     "application/json",
}

# UK-relevant CPV codes for IT/software/data services
# These are EU standard procurement classification codes used in UK tenders
UK_RELEVANT_CPV = {
    "72000000": "IT services",
    "72200000": "Software programming and consultancy",
    "72300000": "Data services",
    "72400000": "Internet services",
    "72500000": "Computer-related services",
    "72600000": "Computer support and consultancy",
    "72700000": "Computer network services",
    "72800000": "Computer audit and testing services",
    "72900000": "Miscellaneous computer-related services",
    "48000000": "Software package and information systems",
    "48600000": "Database and operating software",
    "48800000": "Information systems and servers",
    "48900000": "Miscellaneous software packages",
    "73000000": "Research and development services",
    "79000000": "Business services",
    "79100000": "Legal services",
    "79400000": "Business and management consultancy",
    "79500000": "Office-support services",
    "79600000": "Recruitment services",
    "75000000": "Administration, defence, social security",
    "75100000": "Administration services",
    "75200000": "Provision of services to the community",
    "75231000": "Detention or rehabilitation services",
    "75240000": "Public security, law and order",
    "75241000": "Public security services",
    "75242000": "Law-enforcement services",
    "92000000": "Recreational, cultural, sporting services",
}

# CPV prefixes that are ALWAYS relevant regardless of title
ALWAYS_RELEVANT_CPV = {
    "722", "723", "724", "725", "726", "727", "728", "729",  # IT services
    "480", "486", "488", "489",  # Software
    "752",  # Law enforcement
}

# ---------------------------------------------------------------------------
# SCORING ENGINE (same 9 clusters as US scanner)
# ---------------------------------------------------------------------------
CAPABILITY_CLUSTERS = [
    (
        "Data Integration & Unification", 20,
        [
            "data integration", "data unification", "data fusion", "data silos",
            "data harmonisation", "data harmonization", "enterprise data platform",
            "data consolidation", "data normalisation", "data normalization",
            "data pipeline", "data fabric", "data lake", "data warehouse",
            "data mesh", "data analytics", "analytics platform", "analytics tool",
            "data management", "data management platform", "data solution",
            "data platform", "analytics solution", "business intelligence",
            "software platform", "enterprise software", "cloud platform",
            "information sharing", "master data",
        ],
    ),
    (
        "Investigative & Operational Analytics", 20,
        [
            "investigative analytics", "investigative platform",
            "link analysis", "relationship mapping",
            "situational awareness", "operational intelligence",
            "crime analytics", "crime analysis", "advanced analytics",
            "intelligence platform", "real-time analytics", "predictive analytics",
            "geospatial analysis", "geospatial intelligence",
            "digital evidence", "evidence review platform",
            "evidence analytics", "evidence management platform",
            "digital forensics platform", "investigative data platform",
            "body worn video analytics", "bwv analytics",
        ],
    ),
    (
        "Federated & Enterprise Search", 20,
        [
            "federated search", "enterprise search", "cross-system search",
            "unified search", "cross-database search",
            "multi-source search", "search federation",
            "information retrieval", "knowledge base search",
        ],
    ),
    (
        "Entity Resolution & Record Intelligence", 20,
        [
            "entity resolution", "record deduplication", "record linkage",
            "duplicate records", "identity resolution", "identity matching",
            "record matching", "data deduplication", "entity matching",
            "knowledge graph", "person resolution", "fuzzy matching",
            "probabilistic matching", "golden record", "data quality",
        ],
    ),
    (
        "Secure Government SaaS", 15,
        [
            "cyber essentials", "official sensitive", "jsig", "iso 27001",
            "cloud security", "secure cloud", "government cloud",
            "g-cloud", "gcloud", "govcloud", "zero trust",
            "identity and access management", "iam",
            "audit logging", "il2", "il3", "il4", "official-sensitive",
            "dsp toolkit", "cyber security",
        ],
    ),
    (
        "Public Safety & Law Enforcement", 20,
        [
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
            "national intelligence model", "nim",
            "fusion centre", "fusion center",
            "digital forensics", "digital investigation",
            "body worn video", "body worn camera", "bwv",
            "automatic number plate recognition", "anpr",
            "stop and search data", "use of force data",
        ],
    ),
    (
        "Corrections & Community Supervision", 20,
        [
            "community supervision", "probation", "parole",
            "offender management", "prison management", "prisoner management",
            "case management", "rehabilitation", "reoffending",
            "her majesty's prison", "hmpps", "hmps", "noms",
            "youth offending", "youth justice", "yot",
            "electronic monitoring", "electronic tagging",
            "curfew monitoring", "offender data",
            "community payback", "unpaid work",
        ],
    ),
    (
        "Platform Modernisation & Replacement", 20,
        [
            "platform replacement", "incumbent replacement",
            "platform consolidation", "legacy platform",
            "legacy system", "legacy modernisation", "legacy modernization",
            "platform modernisation", "platform modernization",
            "it modernisation", "it modernization",
            "digital transformation", "cloud migration",
            "software modernisation", "application modernisation",
            "palantir", "demica", "niche", "xhibit",
        ],
    ),
    (
        "AI & Machine Learning", 22,
        [
            "artificial intelligence", "machine learning",
            "ai/ml", "ai platform", "ai solution", "ai system",
            " generative ai", "generative ai ",
            "large language model", "llm",
            "natural language processing", "nlp",
            "computer vision", "predictive model",
            "decision support", "automated analysis",
            "ai-powered", "ai-driven",
            "responsible ai", "explainable ai",
            "ai governance", "ai analytics", "predictive analytics",
        ],
    ),
]

HARD_EXCLUSIONS = [
    # Physical facilities
    "fire suppression", "fire alarm", "hvac", "plumbing", "electrical installation",
    "roof replacement", "flooring", "window replacement", "elevator", "lift maintenance",
    "lighting installation", "cctv installation", "camera installation",
    # Physical goods procurement
    "uniform", "stationery", "office furniture", "catering", "cleaning supplies",
    "medical supplies", "pharmaceutical", "food supply", "laundry",
    # Construction / estates
    "construction", "refurbishment", "building works", "estates management",
    "facilities management", "grounds maintenance", "landscaping", "janitorial",
    # Hardware-only (no software)
    "body armour", "taser", "firearms", "ammunition", "vehicle purchase",
    "fleet procurement", "radio procurement", "handheld radio",
    # Military / defence equipment
    "crypto modernisation", "avionics", "missile", "munitions", "weapons system",
    "aircraft maintenance", "naval vessel", "armoured vehicle",
    # Network/telecom infrastructure
    "vpn service", "ethernet", "network cabling", "structured cabling",
    "fibre optic", "wide area network", "wan circuit",
    "mobile network", "cellular contract",
    # Maintenance agreements (non-software)
    "annual maintenance agreement", "hardware maintenance", "server maintenance",
    "preventive maintenance", "pma maintenance",
    # Professional services unrelated to Peregrine
    "translation services", "interpretation services",
    "legal representation", "solicitor services",
    "financial audit", "accountancy services",
    # Staffing only
    "staffing agency", "temporary staffing", "labour supply",
    "security guard", "door supervision", "close protection",
    # Treatment / social services
    "drug treatment", "alcohol treatment", "mental health treatment",
    "substance misuse", "domestic abuse refuge", "homeless shelter",
    "food bank", "welfare benefits",
    # Training only (not software)
    "firearms training", "first aid training", "personal safety training",
    "physical training", "driver training",
]

TIER_STRONG   = 40
TIER_GOOD     = 15


@dataclass
class Opportunity:
    title:         str
    notice_id:     str
    buyer:         str
    posted_date:   str
    deadline:      str
    description:   str
    url:           str
    opp_type:      str
    source:        str
    cpv_code:      str   = ""
    value_gbp:     float = 0.0
    score:         int   = 0
    tier:          str   = ""
    score_reasons: list  = field(default_factory=list)


def score_opportunity(opp: Opportunity) -> Opportunity:
    """Score against 9 capability clusters. Apply hard exclusions first."""
    text = f" {opp.title} {opp.description} ".lower()

    # Hard exclusions
    for excl in HARD_EXCLUSIONS:
        if excl.lower() in text:
            opp.tier = "⛔ Not a Fit"
            opp.score = 0
            return opp

    # CPV code boost — if CPV is clearly IT/software/law enforcement, boost relevance
    cpv_hint = ""
    if opp.cpv_code:
        cpv_prefix = opp.cpv_code[:3]
        if cpv_prefix in ALWAYS_RELEVANT_CPV:
            cpv_hint = UK_RELEVANT_CPV.get(opp.cpv_code[:8], "")

    text = f" {opp.title} {opp.description} {cpv_hint} ".lower()

    total_score = 0
    reasons     = []
    for cluster_name, cluster_pts, phrases in CAPABILITY_CLUSTERS:
        matched = [p for p in phrases if p in text]
        if matched:
            total_score += cluster_pts
            reasons.append(f"✓ {cluster_name}: matched '{matched[0]}'")

    opp.score         = total_score
    opp.score_reasons = reasons

    if total_score >= TIER_STRONG:
        opp.tier = "🟢 Strong Fit"
    elif total_score >= TIER_GOOD:
        opp.tier = "🟡 Good Fit"
    elif total_score > 0:
        opp.tier = "🔵 Possible Fit"
    else:
        opp.tier = "⚪ Low Fit"

    return opp


def parse_deadline(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt)
        except Exception:
            pass
    return None


def is_expired(opp: Opportunity) -> bool:
    dt = parse_deadline(opp.deadline)
    if dt and dt < datetime.utcnow() - timedelta(days=1):
        return True
    return False


def clean_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ---------------------------------------------------------------------------
# SOURCE 1: FIND A TENDER SERVICE (FTS) — OCDS API
# No API key required. Covers above-threshold UK public tenders.
# ---------------------------------------------------------------------------
FTS_BASE = "https://www.find-tender.service.gov.uk/api/1.0"


def fetch_find_tender(days_back: int = 30) -> list:
    """
    Fetch UK Find a Tender notices via OCDS release packages API.
    Uses date pagination via cursor to retrieve all recent tenders.
    Filters by CPV code prefix and keyword scoring.
    """
    results   = []
    seen_ids  = set()
    today     = datetime.utcnow()
    from_dt   = (today - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
    to_dt     = today.strftime("%Y-%m-%dT23:59:59")

    params  = {
        "updatedFrom": from_dt,
        "updatedTo":   to_dt,
        "stages":      "tender",
        "limit":       100,
    }
    page    = 0
    cursor  = None
    rate_limited = False

    while not rate_limited:
        if cursor:
            params["cursor"] = cursor
        elif page > 0:
            break

        try:
            r = requests.get(
                f"{FTS_BASE}/ocdsReleasePackages",
                params=params,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=30,
            )
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 30))
                print(f"[FTS] Rate limited — waiting {retry}s")
                time.sleep(retry)
                continue
            if r.status_code != 200:
                print(f"[FTS] HTTP {r.status_code}")
                break

            data     = r.json()
            releases = data.get("releases", [])
            if not releases:
                break

            for rel in releases:
                tender = rel.get("tender", {})
                notice_id = rel.get("id", "")
                ocid      = rel.get("ocid", "")
                uid       = notice_id or ocid
                if not uid or uid in seen_ids:
                    continue
                seen_ids.add(uid)

                title      = (tender.get("title") or "").strip()
                desc       = (tender.get("description") or "").strip()
                status     = tender.get("status", "")
                if status in ("cancelled", "withdrawn", "complete"):
                    continue
                if not title:
                    continue

                # Buyer
                buyer_info = rel.get("buyer", {})
                buyer_name = buyer_info.get("name", "Unknown")
                parties    = rel.get("parties", [])
                for p in parties:
                    if "buyer" in p.get("roles", []):
                        buyer_name = p.get("name", buyer_name)
                        break

                # CPV code
                cpv_code = tender.get("classification", {}).get("id", "")
                cpv_desc = tender.get("classification", {}).get("description", "")

                # Deadline
                deadline = (tender.get("tenderPeriod", {}) or {}).get("endDate", "TBD")

                # Value
                value    = 0.0
                val_obj  = tender.get("value", {}) or {}
                if val_obj.get("amount"):
                    value = float(val_obj["amount"])

                # URL
                notice_url = clean_url(
                    f"https://www.find-tender.service.gov.uk/Notice/{notice_id}"
                    if notice_id else f"https://www.find-tender.service.gov.uk"
                )

                # Posted date
                posted = rel.get("date", today.strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]

                opp = Opportunity(
                    title       = title,
                    notice_id   = uid,
                    buyer       = buyer_name,
                    posted_date = posted,
                    deadline    = deadline,
                    description = f"{desc} {cpv_desc}"[:2000],
                    url         = notice_url,
                    opp_type    = rel.get("tag", ["tender"])[0] if rel.get("tag") else "tender",
                    source      = "Find a Tender",
                    cpv_code    = cpv_code,
                    value_gbp   = value,
                )
                results.append(score_opportunity(opp))

            # Pagination
            cursor = data.get("cursor")
            if not cursor or len(releases) < 100:
                break
            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"[FTS] Error: {e}")
            break

    # Filter to only potentially relevant results before returning
    # (scored or CPV prefix matches IT/LE)
    relevant = []
    for o in results:
        cpv_prefix = o.cpv_code[:3] if o.cpv_code else ""
        if o.score > 0 or cpv_prefix in ALWAYS_RELEVANT_CPV:
            relevant.append(o)

    print(f"[FTS] {len(results)} total tenders fetched, {len(relevant)} relevant")
    return relevant


# ---------------------------------------------------------------------------
# SOURCE 2: CONTRACTS FINDER (below-threshold, England, no key)
# ---------------------------------------------------------------------------
CF_BASE = "https://www.contractsfinder.service.gov.uk/Published/Notice/OCDS/Search"


def fetch_contracts_finder(days_back: int = 30) -> list:
    """
    UK Contracts Finder — below-threshold opportunities in England.
    Uses keyword searches via the published notices API.
    """
    results  = []
    seen_ids = set()
    today    = datetime.utcnow()
    from_dt  = (today - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
    to_dt    = today.strftime("%Y-%m-%dT23:59:59")

    # Keyword searches — same terms as US scanner
    SEARCH_TERMS = [
        "data analytics", "data integration", "artificial intelligence",
        "machine learning", "investigative platform", "police analytics",
        "community supervision", "offender management", "digital evidence",
        "law enforcement technology", "public safety platform",
        "records management system", "federated search",
        "entity resolution", "digital transformation",
        "it modernisation", "platform modernisation",
        "crime analytics", "intelligence platform",
        "predictive analytics", "cyber security platform",
    ]

    for term in SEARCH_TERMS:
        try:
            r = requests.get(
                CF_BASE,
                params={
                    "NoticeType":          "Contract notice",
                    "IsPublished":         "true",
                    "SearchText":          term,
                    "PublishedFrom":       from_dt,
                    "PublishedTo":         to_dt,
                    "SortBy":              "PublicationDateDescending",
                    "Size":                100,
                    "Skip":                0,
                },
                headers=HEADERS, timeout=20,
            )
            if r.status_code == 429:
                time.sleep(15)
                continue
            if r.status_code != 200:
                continue

            for rel in r.json().get("releases", []):
                tender    = rel.get("tender", {})
                notice_id = rel.get("id", "")
                if not notice_id or notice_id in seen_ids:
                    continue
                seen_ids.add(notice_id)

                title  = (tender.get("title") or "").strip()
                desc   = (tender.get("description") or "").strip()
                if not title:
                    continue

                buyer_info = rel.get("buyer", {})
                buyer_name = buyer_info.get("name", "Unknown")

                cpv_code = tender.get("classification", {}).get("id", "")
                cpv_desc = tender.get("classification", {}).get("description", "")
                deadline = (tender.get("tenderPeriod", {}) or {}).get("endDate", "TBD")
                value    = float((tender.get("value", {}) or {}).get("amount", 0) or 0)
                posted   = rel.get("date", today.strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]
                notice_url = clean_url(
                    f"https://www.contractsfinder.service.gov.uk/Notice/{notice_id}"
                )

                opp = Opportunity(
                    title       = title,
                    notice_id   = notice_id,
                    buyer       = buyer_name,
                    posted_date = posted,
                    deadline    = deadline,
                    description = f"{desc} {cpv_desc}"[:2000],
                    url         = notice_url,
                    opp_type    = "Contract Notice",
                    source      = "Contracts Finder",
                    cpv_code    = cpv_code,
                    value_gbp   = value,
                )
                results.append(score_opportunity(opp))
            time.sleep(0.3)
        except Exception as e:
            print(f"[ContractsFinder] '{term}': {e}")

    print(f"[Contracts Finder] {len(results)} opportunities")
    return results


# ---------------------------------------------------------------------------
# SOURCE 3: UK COMPETITOR INTELLIGENCE
# UK-specific competitors + Google News UK edition
# ---------------------------------------------------------------------------
UK_COMPETITORS = [
    # US players with major UK presence
    ("Palantir UK",         "Palantir+UK+government+police+law+enforcement"),
    ("Axon UK",             "Axon+UK+police+body+worn+camera+technology"),
    ("Motorola Solutions",  "Motorola+Solutions+UK+police+public+safety"),
    ("IBM i2",              "IBM+i2+UK+law+enforcement+intelligence"),
    ("Databricks",          "Databricks+UK+government+public+sector"),
    # UK-native and Europe-based competitors
    ("Civica",              "Civica+UK+law+enforcement+public+safety+software"),
    ("NEC UK",              "NEC+UK+police+biometric+identity+recognition"),
    ("Hexagon",             "Hexagon+UK+police+CAD+records+management"),
    ("NICE Systems",        "NICE+UK+public+safety+analytics"),
    ("Capita",              "Capita+UK+justice+public+safety+data"),
    ("Sopra Steria",        "Sopra+Steria+UK+police+digital+transformation"),
    ("CGI UK",              "CGI+UK+police+criminal+justice+technology"),
    # Specialist UK competitors
    ("Vigil AI",            "Vigil+AI+UK+police+data+analytics"),
    ("Forensic Analytics",  "Forensic+Analytics+UK+police+data"),
    ("i-nexus",             "i-nexus+UK+law+enforcement+intelligence"),
]


def fetch_uk_competitor_intel() -> list[dict]:
    items      = []
    seen       = set()

    # Google News UK edition per competitor
    for comp_name, query in UK_COMPETITORS:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"
        try:
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; PeregrineUKScanner/1.0)",
                "Accept": "application/rss+xml",
            }, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            count = 0
            for item in root.findall(".//item"):
                if count >= 2:
                    break
                t_el = item.find("title")
                l_el = item.find("link")
                d_el = item.find("description")
                p_el = item.find("pubDate")
                title = (t_el.text or "").strip() if t_el is not None else ""
                desc  = unescape(re.sub(r"<[^>]+>", "", (d_el.text or ""))).strip() if d_el is not None else ""
                url_  = (l_el.text or "").strip() if l_el is not None else ""
                date_ = (p_el.text or "").strip() if p_el is not None else ""
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({
                    "competitor": comp_name,
                    "title":      title,
                    "url":        clean_url(url_),
                    "source":     "Google News (UK)",
                    "date":       date_[:16] if date_ else "",
                    "summary":    desc[:300],
                })
                count += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"[UKCompetitor] {comp_name}: {e}")

    print(f"[UK Competitor Intel] {len(items)} signals")
    return items


# ---------------------------------------------------------------------------
# SOURCE 4: UK INDUSTRY NEWS
# ---------------------------------------------------------------------------
UK_NEWS_FEEDS = [
    {"url": "https://www.publictechnology.net/feed/",             "source": "PublicTechnology"},
    {"url": "https://www.policeoracle.com/rss/news.xml",          "source": "PoliceOracle"},
    {"url": "https://www.gov.uk/search/news-and-communications.atom?keywords=policing+data",
     "source": "GOV.UK Policing"},
    {"url": "https://www.gov.uk/search/news-and-communications.atom?keywords=criminal+justice+technology",
     "source": "GOV.UK CJ Tech"},
    {"url": "https://www.lgcplus.com/feed/",                      "source": "LGC"},
    {"url": "https://www.computerweekly.com/rss/IT-security.xml", "source": "Computer Weekly"},
    {"url": "https://www.ukauthority.com/feed/",                  "source": "UKAuthority"},
    {"url": "https://statescoop.com/feed/",                       "source": "StateScoop"},
    {"url": "https://defensescoop.com/feed/",                     "source": "DefenseScoop"},
]

UK_NEWS_KEYWORDS = [
    "law enforcement", "policing", "public safety", "data analytics",
    "artificial intelligence", "machine learning", "criminal justice",
    "home office", "ministry of justice", "national police", "met police",
    "probation service", "prison service", "hmpps",
    "digital transformation", "records management", "digital evidence",
    "predictive policing", "intelligence platform", "surveillance",
]


def fetch_uk_industry_news() -> list[dict]:
    news = []
    seen = set()
    for feed in UK_NEWS_FEEDS:
        try:
            r = requests.get(feed["url"], headers={
                "User-Agent":  HEADERS["User-Agent"],
                "Accept":      "application/rss+xml, application/xml, text/xml, application/atom+xml",
            }, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            # Handle both RSS and Atom
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in items[:15]:
                t_el = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                l_el = item.find("link")  or item.find("{http://www.w3.org/2005/Atom}link")
                d_el = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
                p_el = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}published")
                title = (t_el.text or "").strip() if t_el is not None else ""
                desc  = unescape(re.sub(r"<[^>]+>", "", (d_el.text or ""))).strip() if d_el is not None else ""
                url_  = ""
                if l_el is not None:
                    url_ = l_el.get("href", l_el.text or "").strip()
                date_ = (p_el.text or "").strip() if p_el is not None else ""
                if not title or title in seen:
                    continue
                combined = f"{title} {desc}".lower()
                if not any(kw in combined for kw in UK_NEWS_KEYWORDS):
                    continue
                seen.add(title)
                news.append({
                    "title":   title,
                    "url":     clean_url(url_),
                    "source":  feed["source"],
                    "date":    date_[:16],
                    "summary": desc[:250],
                })
            time.sleep(0.2)
        except Exception as e:
            print(f"[UKNews] {feed['source']}: {e}")
    print(f"[UK Industry News] {len(news)} articles")
    return news[:15]


# ---------------------------------------------------------------------------
# EMAIL RENDERING
# ---------------------------------------------------------------------------
def deduplicate_and_rank(opps: list) -> list:
    seen = set()
    out  = []
    for o in sorted(opps, key=lambda x: x.score, reverse=True):
        if is_expired(o):
            continue
        key = o.notice_id or o.title[:60].lower()
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def _fmt_value(val: float) -> str:
    if val <= 0:
        return ""
    if val >= 1_000_000:
        return f" · £{val/1_000_000:.1f}m"
    if val >= 1000:
        return f" · £{val/1000:.0f}k"
    return f" · £{val:,.0f}"


def build_opps_section(title: str, opps: list) -> str:
    if not opps:
        return ""
    rows = ""
    for o in opps[:20]:
        link = (
            f'<a href="{o.url}" style="font-weight:700;font-size:14px;color:#003078;text-decoration:none;">{o.title[:120]}</a>'
            if o.url
            else f'<span style="font-weight:700;font-size:14px;color:#111;">{o.title[:120]}</span>'
        )
        reasons_html = ""
        if o.score_reasons:
            bullets = "".join(f"<li>{r}</li>" for r in o.score_reasons[:4])
            reasons_html = (
                '<div style="margin-top:8px;padding:6px 10px;background:#f8fafd;'
                'border-left:3px solid #003078;border-radius:0 4px 4px 0;">'
                '<div style="font-size:11px;font-weight:700;color:#003078;margin-bottom:4px;'
                'text-transform:uppercase;letter-spacing:0.5px;">Why It Fits</div>'
                f'<ul style="margin:0;padding-left:18px;font-size:12px;color:#555;">{bullets}</ul>'
                '</div>'
            )
        deadline_html = ""
        if o.deadline and o.deadline != "TBD":
            dt = parse_deadline(o.deadline)
            if dt:
                days = (dt - datetime.utcnow()).days
                if days <= 7:
                    deadline_html = f' <span style="background:#d4351c;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">Due in {days}d</span>'
                elif days <= 30:
                    deadline_html = f' <span style="background:#f47738;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">Due in {days}d</span>'

        value_str = _fmt_value(o.value_gbp)
        rows += (
            '<div style="border:1px solid #e8e8e8;border-radius:6px;padding:12px;margin-bottom:10px;background:#fff;">'
            f'<div style="margin-bottom:5px;">{link}{deadline_html}</div>'
            f'<div style="font-size:12px;color:#666;">🏛 {o.buyer[:80]} &nbsp;·&nbsp; 📬 {o.posted_date[:10]}{value_str}</div>'
            f'<div style="font-size:11px;color:#999;margin-top:2px;">Source: {o.source} &nbsp;·&nbsp; Score: {o.score}pts'
            + (f' &nbsp;·&nbsp; CPV: {o.cpv_code}' if o.cpv_code else "")
            + f' &nbsp;·&nbsp; <a href="{o.url}" style="color:#003078;">View Notice</a></div>'
            f'{reasons_html}'
            '</div>'
        )
    return (
        f'<div style="margin:20px 0 6px">'
        f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">{title} ({len(opps)})</h2>'
        f'{rows}</div>'
    )


def build_competitor_section_uk(intel_items: list) -> str:
    if not intel_items:
        return ""
    from collections import defaultdict
    grouped = defaultdict(list)
    for item in intel_items:
        grouped[item["competitor"]].append(item)

    rows = ""
    for comp_name in sorted(grouped.keys()):
        stories = grouped[comp_name][:2]
        story_html = ""
        for s in stories:
            link = (
                f'<a href="{s["url"]}" style="color:#003078;text-decoration:none;font-weight:600;">{s["title"][:90]}</a>'
                if s.get("url")
                else f'<span style="font-weight:600;color:#333;">{s["title"][:90]}</span>'
            )
            ns = ("<div style='font-size:12px;color:#555;margin-top:2px;'>" + s.get("summary","")[:200] + "</div>") if s.get("summary") else ""
            story_html += (
                '<div style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f0f0f0;">'
                f'<div style="font-size:13px;">{link}</div>'
                f'<div style="font-size:11px;color:#888;margin-top:2px;">{s["source"]} &middot; {s["date"][:10]}</div>'
                f'{ns}'
                '</div>'
            )
        rows += (
            f'<div style="margin-bottom:14px;">'
            f'<div style="font-weight:700;font-size:12px;color:#555;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;">⚔️ {comp_name}</div>'
            f'{story_html}'
            '</div>'
        )

    return (
        f'<div style="margin:20px 0 6px">'
        f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">🔎 UK Competitor Intelligence ({len(intel_items)} signals)</h2>'
        f'<p style="font-size:12px;color:#888;margin:0 0 12px;">Monitoring: {", ".join(c[0] for c in UK_COMPETITORS)}</p>'
        f'{rows}'
        '</div>'
    )


def build_news_section_uk(news_items: list) -> str:
    if not news_items:
        return ""
    rows = ""
    for item in news_items[:12]:
        link = (
            f'<a href="{item["url"]}" style="color:#003078;text-decoration:none;font-weight:600;">{item["title"][:100]}</a>'
            if item.get("url")
            else f'<span style="font-weight:600;">{item["title"][:100]}</span>'
        )
        ni_sum = ("<div style='font-size:12px;color:#555;margin-top:2px;'>" + item.get("summary","")[:200] + "</div>") if item.get("summary") else ""
        rows += (
            f'<div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #f0f0f0;">'
            f'<div style="font-size:13px;">{link}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px;">{item["source"]} &middot; {item["date"][:10]}</div>'
            f'{ni_sum}'
            '</div>'
        )
    return (
        f'<div style="margin:20px 0 6px">'
        f'<h2 style="font-size:16px;color:#111;border-bottom:2px solid #eee;padding-bottom:5px;">📰 UK Industry News &amp; Market Signals ({len(news_items)})</h2>'
        f'{rows}'
        '</div>'
    )


def _possible_fits_uk(opps: list, shown: set) -> list:
    def _k(o): return (o.notice_id or o.title[:60].lower()).strip()
    unseen = [o for o in opps if _k(o) not in shown]
    possible = [o for o in unseen if "Possible" in o.tier]
    if possible:
        return possible
    KW = ["analytics", "platform", "software", "data integration", "law enforcement analytics"]
    return sorted(
        [o for o in unseen if o.tier not in ("⛔ Not a Fit",) and any(k in o.title.lower() for k in KW)],
        key=lambda x: x.score, reverse=True
    )[:10]


def build_html_email(opps: list, run_date: str,
                     source_counts: dict,
                     competitor_items: list,
                     news_items: list) -> str:

    def _k(o): return (o.notice_id or o.title[:60].lower()).strip()
    def _dedup(lst):
        seen = set(); out = []
        for o in lst:
            k = _k(o)
            if k not in seen: seen.add(k); out.append(o)
        return out

    shown = set()
    strong_list   = _dedup([o for o in opps if "Strong" in o.tier])
    shown.update(_k(o) for o in strong_list)
    good_list     = _dedup([o for o in opps if "Good" in o.tier and _k(o) not in shown])
    shown.update(_k(o) for o in good_list)
    possible_list = _dedup([o for o in opps if "Possible" in o.tier and _k(o) not in shown])
    shown.update(_k(o) for o in possible_list)
    low_list      = _dedup([o for o in opps if o.tier == "⚪ Low Fit" and o.score > 0 and _k(o) not in shown])
    shown.update(_k(o) for o in low_list)

    strong   = len(strong_list)
    good     = len(good_list)
    possible = len(possible_list)

    sc_rows = "".join(
        f'<tr><td style="padding:3px 10px;color:#555;font-size:12px;">{k}</td>'
        f'<td style="padding:3px 10px;font-weight:700;font-size:12px;">{v}</td></tr>'
        for k, v in sorted(source_counts.items())
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#f5f5f5;margin:0;padding:0}}
.wrap{{max-width:720px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden}}
.header{{background:#003078;padding:24px 28px;color:#fff}}
.content{{padding:20px 28px}}
</style></head><body>
<div class="wrap">
<div class="header">
  <div style="font-size:11px;letter-spacing:2px;opacity:0.7;text-transform:uppercase;margin-bottom:4px;">🇬🇧 United Kingdom</div>
  <div style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">🦅 Peregrine UK Daily Scanner</div>
  <div style="font-size:14px;opacity:0.85;margin-top:4px;">{run_date}</div>
  <div style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;">
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">🟢 {strong} Strong</span>
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">🟡 {good} Good</span>
    <span style="background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;">🔵 {possible} Possible</span>
  </div>
</div>
<div class="content">

  <details style="margin-bottom:16px;border:1px solid #eee;border-radius:6px;padding:8px 12px;">
    <summary style="font-size:12px;color:#888;cursor:pointer;">Sources searched today</summary>
    <table style="margin-top:8px;border-collapse:collapse;">{sc_rows}</table>
  </details>

  {build_opps_section("🟢 Strong Fit — Act Now", strong_list)}
  {build_opps_section("🟡 Good Fit — Review Today", good_list)}
  {build_opps_section("🔵 Possible Fit — Review These", _possible_fits_uk(opps, shown))}
  {build_opps_section("⚪ Low Fit — Any Keyword Match", low_list)}
  {build_competitor_section_uk(competitor_items)}
  {build_news_section_uk(news_items)}

</div>
</div></body></html>"""


def send_email(html_body: str, subject: str):
    print(f"[Email] Preparing to send...")
    print(f"[Email]   To:   {EMAIL_TO or 'NOT SET'}")
    print(f"[Email]   From: {EMAIL_FROM or 'NOT SET'}")
    print(f"[Email]   Key:  {'SET (' + str(len(SENDGRID_API_KEY)) + ' chars)' if SENDGRID_API_KEY else 'NOT SET'}")

    if not SENDGRID_API_KEY:
        print("[Email] SKIPPED — no SENDGRID_API_KEY")
        return
    if not EMAIL_TO:
        print("[Email] SKIPPED — no EMAIL_TO")
        return
    if not EMAIL_FROM:
        print("[Email] SKIPPED — no EMAIL_FROM")
        return

    payload = {
        "personalizations": [{"to": [{"email": EMAIL_TO}]}],
        "from":    {"email": EMAIL_FROM, "name": "Peregrine UK Scanner"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 202):
            print(f"[Email] ✓ Sent successfully to {EMAIL_TO} (HTTP {r.status_code})")
        else:
            print(f"[Email] ✗ Send failed — HTTP {r.status_code}")
            print(f"[Email]   Response: {r.text[:500]}")
            # Common causes:
            # 401 = bad API key
            # 403 = sender not verified in SendGrid
            # 400 = malformed request
            if r.status_code == 403:
                print("[Email]   HINT: Sender address not verified in SendGrid.")
                print(f"[Email]   Go to sendgrid.com → Settings → Sender Authentication")
                print(f"[Email]   and verify: {EMAIL_FROM}")
    except Exception as e:
        print(f"[Email] Error: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    today    = datetime.utcnow()
    run_date = today.strftime("%d %B %Y")  # UK date format
    print(f"\n{'='*60}")
    print(f"  Peregrine UK Daily Scanner — {run_date}")
    print(f"{'='*60}")
    print(f"[Config] SENDGRID_API_KEY: {'SET' if SENDGRID_API_KEY else 'NOT SET'}")
    print(f"[Config] EMAIL_TO:         {EMAIL_TO}")

    source_counts = {}
    all_opps      = []

    print("\n[Find a Tender] Fetching UK tenders (last 30 days)...")
    try:
        fts_opps = fetch_find_tender(days_back=30)
        source_counts["Find a Tender"] = len(fts_opps)
        all_opps.extend(fts_opps)
    except Exception as e:
        print(f"[Find a Tender] FAILED: {e}")
        source_counts["Find a Tender"] = 0

    print("\n[Contracts Finder] Fetching below-threshold opps...")
    try:
        cf_opps = fetch_contracts_finder(days_back=30)
        source_counts["Contracts Finder"] = len(cf_opps)
        all_opps.extend(cf_opps)
    except Exception as e:
        print(f"[Contracts Finder] FAILED: {e}")
        source_counts["Contracts Finder"] = 0

    print(f"\n[Scoring] Deduplicating {len(all_opps)} raw results...")
    ranked = deduplicate_and_rank(all_opps)
    strong   = sum(1 for o in ranked if "Strong" in o.tier)
    good     = sum(1 for o in ranked if "Good" in o.tier)
    possible = sum(1 for o in ranked if "Possible" in o.tier)
    print(f"[Tiers] 🟢 {strong} Strong  🟡 {good} Good  🔵 {possible} Possible")

    print("\n[UK Competitor Intel] Fetching...")
    try:
        competitor_items = fetch_uk_competitor_intel()
        source_counts["Competitor Intel"] = len(competitor_items)
    except Exception as e:
        print(f"[UK Competitor Intel] FAILED: {e}")
        competitor_items = []

    print("\n[UK Industry News] Fetching...")
    try:
        news_items = fetch_uk_industry_news()
        source_counts["Industry News"] = len(news_items)
    except Exception as e:
        print(f"[UK Industry News] FAILED: {e}")
        news_items = []

    # Subject line
    if strong == 0 and good == 0:
        subject = f"Peregrine UK Scanner | No Strong Matches Today | {today.strftime('%d %b')}"
    elif strong >= 1:
        subject = f"Peregrine UK Scanner | {strong} Strong · {good} Good · {possible} Possible | {today.strftime('%d %b')}"
    else:
        subject = f"Peregrine UK Scanner | {good} Good · {possible} Possible Fits | {today.strftime('%d %b')}"

    html = build_html_email(ranked, run_date, source_counts, competitor_items, news_items)
    send_email(html, subject)

    fname = f"uk_digest_{today.strftime('%Y%m%d')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[Done] Digest saved: {fname}")
    print(f"[Done] Subject: {subject}")


if __name__ == "__main__":
    main()
