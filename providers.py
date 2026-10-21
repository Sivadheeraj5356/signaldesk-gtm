"""ICP-driven company discovery through legitimate free JSON APIs.

The workspace profile (industry, what-you-sell, region) generates the queries;
providers return candidates with full provenance (provider, query, source URL).
No keyless scraping, no logged-in sources. Key-based providers (Brave) are
operator-configured via environment and report 'not_configured' without a key.
Candidates are always UNVERIFIED until researched.
"""
import json, os, re, urllib.request, urllib.parse
import discover

UA = {'User-Agent': 'SignalDeskResearch/0.1 (public API access; contact via workspace owner)'}
TIMEOUT = 12

def _get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(2000000))

STOP = {'software','company','companies','the','and','for','with','your','their','that','this','from','into','platform','solution','solutions','business','service','services','best','top','tool','tools','app','apps','system','systems','b2b','saas','person','people','persons','team','teams','size','range'}

def keywords(text, cap=6):
    words = re.findall(r'[A-Za-z][A-Za-z0-9+-]{2,}', (text or '').lower())
    seen, out = set(), []
    for w in words:
        if w in STOP or w in seen: continue
        seen.add(w); out.append(w)
        if len(out) >= cap: break
    return out

def build_icp_queries(cfg):
    """Queries derived from the workspace's own profile, not hardcoded."""
    qs = []
    ind = (cfg.get('industry') or '').strip()
    kw = keywords(cfg.get('company_details') or cfg.get('offer') or '')
    region = (cfg.get('region') or '').strip()
    if ind and kw: qs.append(' '.join([ind] + kw[:3]) + ' company')
    if kw: qs.append(' '.join(kw[:4]) + ' company')
    if ind: qs.append(ind + ' software company')
    if region and kw: qs.append(' '.join(kw[:3]) + ' ' + region + ' startup')
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen: seen.add(q.lower()); out.append(q)
    return out[:4]

def clean_company_name(title):
    t = re.sub(r'\s*\((company|software|website|business)\)\s*$', '', title or '', flags=re.I)
    t = re.sub(r',?\s+(Inc|LLC|Ltd|GmbH|Corp|Corporation)\.?$', '', t, flags=re.I)
    return t.strip() or title

def domain_of(url):
    h = (urllib.parse.urlparse(url if '://' in url else 'https://' + url).hostname or '').lower()
    return h.removeprefix('www.')

def wiki_parse_results(search_json, entities_json, query):
    """Pure: join Wikipedia search hits with Wikidata official websites."""
    out = []
    entities = (entities_json or {}).get('entities', {})
    by_title = {}
    for e in entities.values():
        site = (e.get('sitelinks', {}) or {}).get('enwiki', {}).get('title')
        p856 = e.get('claims', {}).get('P856', [])
        official = None
        for claim in p856:
            snak = claim.get('mainsnak', {})
            if 'datavalue' in snak: official = snak['datavalue']['value']; break
        if site: by_title[site] = official
    for hit in (search_json or {}).get('query', {}).get('search', []):
        title = hit.get('title', '')
        official = by_title.get(title)
        if not official: continue  # not a company with a public official site
        dom = domain_of(official)
        if not dom or '.' not in dom: continue
        bare = dom
        if any(bare == d or bare.endswith('.' + d) for d in discover.NON_COMPANY): continue
        out.append(dict(company=clean_company_name(title), domain=bare, url='https://' + bare + '/',
                        status='unverified', provider='wikipedia', provider_query=query,
                        source='https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')),
                        evidence='Wikipedia article names this official website; not verified'))
    return out

def wikipedia_candidates(query, limit=12):
    s = _get_json('https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=' +
                  urllib.parse.quote(query) + '&format=json&srlimit=' + str(limit))
    titles = [h['title'] for h in s.get('query', {}).get('search', [])]
    if not titles: return []
    e = _get_json('https://www.wikidata.org/w/api.php?action=wbgetentities&sites=enwiki&titles=' +
                  urllib.parse.quote('|'.join(titles)) + '&props=claims|sitelinks&format=json')
    return wiki_parse_results(s, e, query)

def hn_parse_results(hits_json, query):
    """Pure: company candidates from HN Algolia story hits."""
    out = []
    for h in (hits_json or {}).get('hits', []):
        url = h.get('url') or ''
        if not url: continue
        dom = domain_of(url)
        if not dom or '.' not in dom: continue
        if any(dom == d or dom.endswith('.' + d) for d in discover.NON_COMPANY + ('news.ycombinator.com',)): continue
        out.append(dict(company=discover.clean_name(h.get('title', ''), dom), domain=dom,
                        url='https://' + dom + '/', status='unverified', provider='hackernews',
                        provider_query=query,
                        source='https://news.ycombinator.com/item?id=' + str(h.get('objectID', '')),
                        evidence='Company site linked from a Hacker News story; not verified'))
    return out

def hackernews_candidates(query, limit=12):
    d = _get_json('https://hn.algolia.com/api/v1/search?query=' + urllib.parse.quote(query) +
                  '&tags=story&hitsPerPage=' + str(limit))
    return hn_parse_results(d, query)

def brave_candidates(query, limit=12):
    key = os.environ.get('SIGNALDESK_BRAVE_API_KEY', '')
    if not key: return 'not_configured'
    req = urllib.request.Request('https://api.search.brave.com/res/v1/web/search?q=' +
                                 urllib.parse.quote(query) + '&count=' + str(limit),
                                 headers={'Accept': 'application/json', 'X-Subscription-Token': key})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read(2000000))
    out = []
    for w in d.get('web', {}).get('results', []):
        dom = domain_of(w.get('url', ''))
        if not dom or '.' not in dom: continue
        if any(dom == x or dom.endswith('.' + x) for x in discover.NON_COMPANY): continue
        out.append(dict(company=discover.clean_name(w.get('title', ''), dom), domain=dom,
                        url='https://' + dom + '/', status='unverified', provider='brave',
                        provider_query=query, source=w.get('url', ''),
                        evidence='Web search result; not verified'))
    return out

def icp_candidates(cfg, limit=30, budget=45):
    """Aggregate candidates across configured providers for the workspace ICP."""
    import time as _t
    start = _t.monotonic()
    queries = build_icp_queries(cfg)
    if not queries: raise ValueError('Complete your company profile first: industry and what you sell drive discovery.')
    allc, seen, providers = [], set(), {}
    for q in queries:
        for name, fn in [('wikipedia', wikipedia_candidates), ('hackernews', hackernews_candidates), ('brave', brave_candidates)]:
            if _t.monotonic() - start > budget:
                providers.setdefault('stopped', 'time budget reached; partial results')
                return dict(queries=queries, candidates=allc, providers=providers)
            try: res = fn(q)
            except Exception:
                providers.setdefault(name, 'error'); continue
            if res == 'not_configured': providers[name] = 'not_configured'; continue
            providers[name] = providers.get(name, 0) + len(res)
            for c in res:
                if c['domain'] in seen: continue
                seen.add(c['domain']); allc.append(c)
                if len(allc) >= limit: return dict(queries=queries, candidates=allc, providers=providers)
    return dict(queries=queries, candidates=allc, providers=providers)
