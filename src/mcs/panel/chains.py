"""Owner-group normalisation and Wikipedia chain-list supplements (SPEC §4.2).

Chain lists are fetched as ordinary article pages (``/wiki/<Title>``): Wikimedia's robots.txt
disallows ``/w/`` (which includes ``/w/api.php?action=parse``) for ``*``, so the API is not used.
They are used only to fill ``owner_group`` (match by registered domain or normalised title)
and to add missing dailies when the list gives a domain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser

from mcs.panel.http import PoliteClient, RobotsDisallowed, safe_name
from mcs.panel.normalize import registered_domain

UNKNOWN = "independent/unknown"

# (regex on an owner/parent label, canonical group). First match wins.
OWNER_RULES: list[tuple[str, str]] = [
    (r"gannett|usa today (co|network)|gatehouse|new media investment|dow jones local media|ottaway",
     "Gannett/USA Today Co."),
    (r"lee enterprises|berkshire hathaway|bh media", "Lee Enterprises"),
    (r"mcclatchy|knight.?ridder", "McClatchy"),
    (r"hearst", "Hearst"),
    (r"advance (publications|local|media)|alabama media group|nj advance|mlive media|"
     r"oregonian media|syracuse media|newhouse", "Advance"),
    (r"medianews|digital first media|alden global|tribune publishing|\btronc\b|"
     r"tribune company|california newspapers partnership", "MediaNews/Alden"),
    (r"\bcnhi\b|community newspaper holdings|retirement systems of alabama", "CNHI"),
    (r"adams publishing", "Adams"),
    (r"ogden newspapers|ogden publications", "Ogden"),
    (r"carpenter media", "Carpenter Media Group"),
    (r"newsquest|archant", "Newsquest"),
    (r"reach plc|trinity mirror|local world|northern (&|and) shell|express newspapers|"
     r"mirror group|^reach$", "Reach"),
    (r"national world|jpimedia|johnston press", "National World"),
    (r"dmg media|daily mail and general trust|associated newspapers", "DMG Media"),
    (r"news uk|news international|times newspapers", "News UK"),
    (r"news corp|dow jones & company|nyp holdings", "News Corp"),
    (r"guardian media group|scott trust", "Guardian Media Group"),
    (r"new york times company", "New York Times Co."),
    (r"\bcox (enterprises|media)", "Cox"),
    (r"paxton media", "Paxton Media Group"),
    (r"forum communications", "Forum Communications"),
    (r"wehco", "WEHCO Media"),
    (r"axel springer", "Axel Springer"),
    (r"iliffe", "Iliffe Media"),
    (r"tindle", "Tindle"),
    (r"midland news association|express & star", "MNA"),
    (r"black press", "Black Press"),
    (r"sinclair", "Sinclair"),
    (r"nexstar", "Nexstar"),
    (r"boone newspapers", "Boone Newspapers"),
    (r"champion media", "Champion Media"),
    (r"aim media", "AIM Media"),
    (r"landmark (media|communications)", "Landmark"),
    (r"pamplin", "Pamplin Media Group"),
    (r"national trust for local news", "National Trust for Local News"),
    (r"vuga", "VUGA"),
    (r"bbc|british broadcasting", "BBC"),
]
_OWNER_RES = [(re.compile(p, re.I), g) for p, g in OWNER_RULES]

_SUFFIX_RE = re.compile(r",?\s+(inc\.?|llc|l\.l\.c\.|ltd\.?|limited|plc|corp\.?|corporation|"
                        r"company|co\.)$", re.I)


def canonical_owner(label: str) -> str | None:
    """Canonical group for a label if it matches a known chain, else None."""
    if not label:
        return None
    for rx, g in _OWNER_RES:
        if rx.search(label):
            return g
    return None


def clean_owner(label: str) -> str:
    s = (label or "").strip()
    for _ in range(2):
        s = _SUFFIX_RE.sub("", s).strip()
    return s


def resolve_owner(labels_by_priority: list[str]) -> str:
    """Pick the owner group from candidate labels ordered by priority (P127 direct, P749,
    owner's parent). A canonical chain match anywhere wins; else the first raw label."""
    for lab in labels_by_priority:
        g = canonical_owner(lab)
        if g:
            return g
    for lab in labels_by_priority:
        if lab and lab.strip() and not re.fullmatch(r"Q\d+", lab.strip()):
            return clean_owner(lab)
    return UNKNOWN


def norm_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Wikipedia chain lists: (page title candidates, canonical group). Missing pages are logged.
CHAIN_PAGES: list[tuple[list[str], str]] = [
    (["List of assets owned by USA Today Co.", "List of assets owned by Gannett"], "Gannett/USA Today Co."),
    (["List of newspapers owned by Lee Enterprises", "Lee Enterprises"], "Lee Enterprises"),
    (["McClatchy"], "McClatchy"),
    (["Hearst Newspapers", "Hearst Communications"], "Hearst"),
    (["Advance Local"], "Advance"),
    (["MediaNews Group", "Tribune Publishing"], "MediaNews/Alden"),
    (["CNHI"], "CNHI"),
    (["Adams Publishing Group"], "Adams"),
    (["Ogden Newspapers"], "Ogden"),
    (["Carpenter Media Group"], "Carpenter Media Group"),
]


@dataclass
class ChainResult:
    by_domain: dict[str, str] = field(default_factory=dict)
    by_title: dict[str, str] = field(default_factory=dict)
    added_domains: dict[str, tuple[str, str]] = field(default_factory=dict)  # dom -> (title, group)
    log: list[dict] = field(default_factory=list)


def parse_chain_page(html: str, group: str, res: ChainResult) -> int:
    """Collect newspaper titles and external domains from list items / table rows."""
    tree = LexborHTMLParser(html)
    n = 0
    body = tree.css_first("#mw-content-text") or tree.body
    if body is None:
        return 0
    for node in body.css("li, tr"):
        a_ext = [a.attributes.get("href", "") for a in node.css("a.external, a[rel~=nofollow]")]
        title_node = node.css_first("i a, i, a, td")
        title = title_node.text(strip=True) if title_node else ""
        if title and len(title) < 80:
            res.by_title.setdefault(norm_title(title), group)
            n += 1
        for href in a_ext:
            d = registered_domain(href)
            if d and "wiki" not in d:
                res.by_domain.setdefault(d, group)
                res.added_domains.setdefault(d, (title, group))
    return n


def fetch_chains(client: PoliteClient) -> ChainResult:
    res = ChainResult()
    host_blocked = None
    for titles, group in CHAIN_PAGES:
        done = False
        for t in titles:
            url = "https://en.wikipedia.org/wiki/" + quote(t.replace(" ", "_"))
            if host_blocked:
                res.log.append({"page": t, "status": "skipped", "note": host_blocked})
                done = True
                break
            try:
                body, meta = client.get(url, "wikipedia/" + safe_name(t) + ".html")
            except RobotsDisallowed:
                res.log.append({"page": t, "status": "robots-disallowed"})
                continue
            except Exception as e:
                res.log.append({"page": t, "status": "error", "note": repr(e)})
                continue
            st = meta.get("status")
            if st == 200:
                n = parse_chain_page(body.decode("utf-8", "replace"), group, res)
                res.log.append({"page": t, "status": 200, "entries": n})
                done = True
                break
            if st == 403:
                host_blocked = (f"en.wikipedia.org answered 403 to our client "
                                f"({body[:160].decode('utf-8', 'replace').strip()}); "
                                f"not retried, chain supplements skipped")
                res.log.append({"page": t, "status": 403, "note": host_blocked})
                done = True
                break
            res.log.append({"page": t, "status": st, "note": "page missing; trying next name"})
        if not done:
            res.log.append({"page": " | ".join(titles), "status": "not found"})
    return res
