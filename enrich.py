"""Public contact discovery from a company's OWN published pages.

Scope discipline: only business contact data the company itself publishes on its
site (mailto:, tel:, LinkedIn links and visible emails on /contact, /about,
/team, /imprint-style pages). No logged-in sources, no pattern guessing as fact.
Every item carries its source page URL and a status: published | inferred | missing.
"""
import re, datetime
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser
import research

CONTACT_PATHS = ['/contact', '/contact-us', '/about', '/about-us', '/team', '/about/team', '/imprint', '/impressum']
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
GENERIC_PREFIXES = {'info','hello','contact','sales','support','hi','mail','office','team','enquiries','inquiry','careers','jobs','press','media','general','admin','help','business'}
EMAIL_PLACEHOLDER_RE = re.compile(r'^(example|email|your|name|user)@|@(example|domain)\.|\.(example|test)$|@sentry|\.\w{2}\.(js|png|jpg|svg)$', re.I)

class ContactHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.mailtos, self.tels, self.linkedins, self.text_parts = [], [], [], []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ['script','style','noscript','svg']: self.skip += 1
        href = d.get('href','')
        if tag == 'a' and href:
            if href.lower().startswith('mailto:'):
                self.mailtos.append(href[7:].split('?')[0].strip())
            elif href.lower().startswith('tel:'):
                self.tels.append(href[4:].strip())
            elif 'linkedin.com/' in href:
                self.linkedins.append(href)
    def handle_endtag(self, tag):
        if tag in ['script','style','noscript','svg']: self.skip = max(0, self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.text_parts.append(data)

def label_email(addr):
    local = addr.split('@')[0].lower()
    return 'generic' if local in GENERIC_PREFIXES else 'personal'

def extract_contacts(html, page_url):
    """Pull published contacts from one page's HTML. Pure function, fully testable."""
    p = ContactHTML(); p.feed(html)
    out, seen = [], set()
    def add(kind, value, label=None):
        value = value.strip()
        if not value or (kind, value.lower()) in seen: return
        seen.add((kind, value.lower()))
        out.append(dict(type=kind, value=value, label=label or '', status='published',
                        source_url=page_url, source='company website'))
    for m in p.mailtos:
        if EMAIL_RE.fullmatch(m) and not EMAIL_PLACEHOLDER_RE.search(m):
            add('email', m, label_email(m))
    for t in p.tels:
        digits = re.sub(r'\D', '', t)
        if 7 <= len(digits) <= 15: add('phone', t, 'business')
    for l in p.linkedins:
        clean = l.split('?')[0].rstrip('/')
        if re.fullmatch(r'https?://(www\.)?linkedin\.com/(in|company)/[A-Za-z0-9_\-.%]+', clean):
            add('linkedin', clean.replace('http://','https://'), 'company' if '/company/' in clean else 'personal')
    text = ' '.join(p.text_parts)
    for m in set(EMAIL_RE.findall(text)):
        if not EMAIL_PLACEHOLDER_RE.search(m):
            add('email', m, label_email(m))
    return out

def _robots_allows(host, url):
    try:
        status, _, data, _ = research.fetch('https://' + host + '/robots.txt')
    except ValueError:
        return False
    if status == 404: return True
    if status != 200: return False
    rp = RobotFileParser(); rp.parse(data.decode('utf-8', errors='replace').splitlines())
    return rp.can_fetch(research.UA, url)

def contacts_for_domain(domain, max_pages=6):
    """Fetch a company's public pages and extract published contacts.
    Raises ValueError with a human reason when nothing can be collected."""
    host = domain.removeprefix('www.')
    pages, contacts, errors = ['https://' + host + '/'], [], []
    for path in CONTACT_PATHS:
        if len(pages) >= max_pages: break
        pages.append('https://' + host + path)
    fetched = 0
    for url in pages[:max_pages]:
        if not _robots_allows(host, url):
            errors.append(url + ': robots policy'); continue
        try:
            status, typ, data, final = research.fetch(url, redirects=1)
        except Exception as e:
            errors.append(url + ': ' + str(e)[:80]); continue
        if status != 200 or 'text/html' not in typ.lower(): continue
        fetched += 1
        contacts.extend(extract_contacts(data.decode('utf-8', errors='replace'), final))
    # dedupe across pages, keeping first source
    seen, deduped = set(), []
    for c in contacts:
        k = (c['type'], c['value'].lower())
        if k not in seen: seen.add(k); deduped.append(c)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for c in deduped: c['fetched_at'] = now
    return dict(domain=host, contacts=deduped, pages_fetched=fetched,
                fetched_at=now, errors=errors[:5],
                method='Company-published pages only; robots-respecting; no logged-in or third-party sources')
