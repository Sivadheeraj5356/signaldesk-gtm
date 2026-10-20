"""Bounded public HTML research. No cookies, scripts, contact collection or private IPs."""
import socket, ipaddress, http.client, ssl, re, hashlib, datetime
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from html.parser import HTMLParser
UA='SignalDeskResearch/0.1'
MAX_BYTES=500000
class PublicHTML(HTMLParser):
    def __init__(self): super().__init__();self.skip=0;self.title_mode=False;self.title=[];self.parts=[];self.description=''
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in ['script','style','noscript','svg']:self.skip+=1
        if tag=='title':self.title_mode=True
        if tag=='meta' and d.get('name','').lower()=='description':self.description=d.get('content','')[:600]
    def handle_endtag(self,tag):
        if tag in ['script','style','noscript','svg']:self.skip=max(0,self.skip-1)
        if tag=='title':self.title_mode=False
    def handle_data(self,data):
        if self.skip:return
        data=re.sub(r'\s+',' ',data).strip()
        if self.title_mode:self.title.append(data)
        if data:self.parts.append(data)

def public_target(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in [None,443]:raise ValueError('Research requires an HTTPS URL on port 443 with no credentials')
    host=p.hostname
    if host.endswith(('.local','.internal','.localhost','.example')) or host=='localhost':raise ValueError('Only public websites may be researched')
    try: addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError:raise ValueError('Website DNS lookup failed')
    ips=list(dict.fromkeys(a[4][0] for a in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('Private, reserved and mixed DNS destinations are blocked')
    return p,ips[0]

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ip):super().__init__(host,timeout=8,context=ssl.create_default_context());self.ip=ip
    def connect(self):
        sock=socket.create_connection((self.ip,443),timeout=self.timeout)
        try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception:sock.close();raise

def fetch(url,redirects=2):
    p,ip=public_target(url);conn=PinnedHTTPS(p.hostname,ip)
    try:
        target=(p.path or '/')+('?' + p.query if p.query else '')
        conn.request('GET',target,headers={'User-Agent':UA,'Accept':'text/html,text/plain','Accept-Encoding':'identity'})
        r=conn.getresponse()
        if r.status in [301,302,303,307,308]:
            if redirects<=0:raise ValueError('Too many redirects')
            location=r.getheader('Location')
            if not location:raise ValueError('Redirect has no destination')
            destination=urljoin(url,location)
            if urlparse(destination).hostname!=p.hostname:raise ValueError('Cross-domain redirect blocked; use manual evidence')
            return fetch(destination,redirects-1)
        data=r.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('Website exceeds 500 KB research limit')
        return r.status,r.getheader('Content-Type',''),data,url
    finally:conn.close()

def research(url):
    p,_=public_target(url)
    robot_url='https://'+p.netloc+'/robots.txt'
    status,typ,data,_=fetch(robot_url)
    if status==200:
        rp=RobotFileParser();rp.parse(data.decode('utf-8',errors='replace').splitlines())
        if not rp.can_fetch(UA,url):raise ValueError('Website robots.txt disallows this research')
        delay=rp.crawl_delay(UA) or rp.crawl_delay('*')
        if delay and delay>0:raise ValueError('Website requests a crawl delay. Use a source note instead of automated research.')
    elif status!=404:raise ValueError('Could not confirm robots policy. Add evidence manually instead.')
    status,typ,data,final=fetch(url)
    if status!=200:raise ValueError('Website returned HTTP '+str(status))
    if not any(t in typ.lower() for t in ['text/html','text/plain']):raise ValueError('Only public HTML and text pages are supported')
    parser=PublicHTML();parser.feed(data.decode('utf-8',errors='replace'))
    content=' '.join(parser.parts)
    # Avoid collecting personal contact identifiers as a side effect of company research.
    content=re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[email omitted]',content)
    content=re.sub(r'(?:\+?\d[\d ()-]{8,}\d)', '[phone-like number omitted]',content)
    excerpt=content[:2200]
    def redact(value):
        value=re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[email omitted]',value)
        return re.sub(r'(?:\+?\d[\d ()-]{8,}\d)', '[phone-like number omitted]',value)
    if not excerpt.strip():raise ValueError('No readable public content found')
    return dict(title=redact(' '.join(parser.title)[:300]),description=redact(parser.description),excerpt=excerpt,url=final,fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(data).hexdigest(),verified=False,method='Bounded public HTML fetch; no independent fact verification')


def bounded_research(url,timeout=25):
    """A separate process makes the deadline cover DNS and slow HTTP bodies too."""
    import subprocess,sys,json
    try:
        r=subprocess.run([sys.executable,str(__file__),url],capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired:raise ValueError('Research exceeded the 25-second total deadline; no evidence was replaced')
    try:result=json.loads(r.stdout)
    except Exception:raise ValueError('Research worker failed; no evidence was replaced')
    if not result.get('ok'):raise ValueError(result.get('error','Research failed'))
    return result['data']

if __name__=='__main__':
    import sys,json
    try:print(json.dumps({'ok':True,'data':research(sys.argv[1])}))
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)[:300]}))
