"""Candidate-company discovery from ONE user-supplied public source page.

The user points at a public page that lists companies (a directory, an event
sponsor page, a listicle). We fetch that single page, robots-respecting, and
extract the outbound company sites it links to. Candidates are UNVERIFIED:
they are companies the source page linked to, nothing more. No search-engine
scraping, no logged-in sources, no pattern guessing.
"""
import re, datetime
from urllib.parse import urlparse
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser
import research

MAX_CANDIDATES = 50
NON_COMPANY = (
    'linkedin.com','x.com','twitter.com','facebook.com','instagram.com','youtube.com',
    'tiktok.com','github.com','gitlab.com','medium.com','substack.com','google.com',
    'apple.com','wikipedia.org','reddit.com','quora.com','pinterest.com','crunchbase.com',
    'producthunt.com','g2.com','capterra.com','trustpilot.com','wordpress.com','blogspot.com',
    't.co','bit.ly','ow.ly','buff.ly','tinyurl.com','youtu.be','wa.me','whatsapp.com',
    'discord.com','slack.com','notion.so','docs.google.com','support.google.com',
    'wsj.com','nytimes.com','bloomberg.com','reuters.com','bbc.com','bbc.co.uk','cnn.com',
    'techcrunch.com','theverge.com','forbes.com','cnbc.com','ft.com','theguardian.com','businessinsider.com',
    'wikimedia.org','wikidata.org','mediawiki.org','wikimediafoundation.org','wiktionary.org',
    'wikibooks.org','wikinews.org','wikiquote.org','wikisource.org','wikiversity.org','wikivoyage.org',
)
CTA_WORDS = re.compile(r'^(visit|website|site|learn more|read more|more|click|here|link|demo|sign ?up|get started|home|view|open)$', re.I)

class LinkHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self._a = None; self._text = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            d = dict(attrs); self._a = d.get('href', ''); self._text = []
    def handle_data(self, data):
        if self._a is not None: self._text.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self._a is not None:
            self.links.append((self._a, ' '.join(self._text)))
            self._a = None; self._text = []

def name_from_domain(host):
    base = host.split('.')[0]
    return re.sub(r'[-_]+', ' ', base).strip().title() or host

def clean_name(text, host):
    t = re.sub(r'\s+', ' ', text or '').strip(' .|-\u2013\u2014')
    if not t or len(t) > 60 or CTA_WORDS.match(t) or 'http' in t.lower() or '?' in t or t.count(' ') > 4:
        return name_from_domain(host)
    return t

def extract_candidates(html, source_host):
    """Pure: outbound company links from one page. Testable without network."""
    p = LinkHTML(); p.feed(html)
    out, seen, skipped = [], set(), 0
    for href, text in p.links:
        href = (href or '').strip()
        if not href.lower().startswith(('http://', 'https://')): continue
        u = urlparse(href)
        host = (u.hostname or '').lower()
        if not host or host == source_host or host.endswith('.' + source_host): continue
        bare = host.removeprefix('www.')
        if any(bare == d or bare.endswith('.' + d) for d in NON_COMPANY): skipped += 1; continue
        if bare.count('.') < 1 or '.' not in bare: continue
        if bare in seen: continue
        seen.add(bare)
        out.append(dict(company=clean_name(text, bare), domain=bare,
                        url='https://' + bare + '/', status='unverified',
                        evidence='Listed on a public source page; not verified'))
        if len(out) >= MAX_CANDIDATES: break
    return out, skipped

def discover_from_page(url):
    """Fetch one public source page and extract candidate companies."""
    p, _ = research.public_target(url)
    host = p.hostname.lower().removeprefix('www.')
    try:
        status, _, data, _ = research.fetch('https://' + p.netloc + '/robots.txt')
    except ValueError:
        raise ValueError('Could not confirm the source page robots policy; discovery skipped')
    if status == 200:
        rp = RobotFileParser(); rp.parse(data.decode('utf-8', errors='replace').splitlines())
        if not rp.can_fetch(research.UA, url):
            raise ValueError('The source page robots.txt disallows this fetch')
    elif status != 404:
        raise ValueError('Could not confirm the source page robots policy; discovery skipped')
    status, typ, data, final = research.fetch(url, redirects=1)
    if status != 200: raise ValueError('Source page returned HTTP ' + str(status))
    if 'text/html' not in typ.lower(): raise ValueError('Source page is not HTML')
    html = data.decode('utf-8', errors='replace')
    candidates, skipped = extract_candidates(html, urlparse(final).hostname.lower().removeprefix('www.'))
    for c in candidates: c['source'] = final
    return dict(source_url=final, candidates=candidates, skipped_noncompany=skipped,
                fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                method='One user-supplied public page; outbound company links only; unverified until researched')
