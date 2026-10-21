import discover

SAMPLE = '''<html><body>
<h1>Top payroll tools</h1>
<a href="https://www.gusto.com/">Gusto</a>
<a href="https://gusto.com/pricing">Gusto pricing</a>
<a href="https://rippling.com">Rippling - HR platform</a>
<a href="https://www.linkedin.com/company/gusto">Gusto on LinkedIn</a>
<a href="https://twitter.com/gusto">@gusto</a>
<a href="https://x.com/rippling">rippling x</a>
<a href="https://bit.ly/3abc">short link</a>
<a href="mailto:editor@blogsite.com">email us</a>
<a href="/about">internal about</a>
<a href="https://blogsite.com/about">same site</a>
<a href="https://deel.com/"><img></a>
<a href="https://papayaglobal.com">Visit</a>
<a href="https://sub.blogsite.com/post">subdomain of source</a>
</body></html>'''

def test_extract_company_candidates():
    cs, skipped = discover.extract_candidates(SAMPLE, 'blogsite.com')
    domains = [c['domain'] for c in cs]
    assert 'gusto.com' in domains
    assert domains.count('gusto.com') == 1  # dedupe across paths/www
    assert 'rippling.com' in domains
    assert 'deel.com' in domains
    assert 'papayaglobal.com' in domains
    # social, shorteners, internal, same-site, subdomain excluded
    assert not any('linkedin' in d or 'twitter' in d or 'x.com' in d or 'bit.ly' in d for d in domains)
    assert not any('blogsite.com' in d for d in domains)
    assert skipped >= 3  # linkedin, twitter, x, bit.ly
    # names: anchor text when sane, domain-derived for CTA/icon links
    by = {c['domain']: c for c in cs}
    assert by['gusto.com']['company'] == 'Gusto'
    assert by['deel.com']['company'] == 'Deel'
    assert by['papayaglobal.com']['company'] == 'Papayaglobal'
    # every candidate unverified with an honest evidence note
    assert all(c['status'] == 'unverified' and 'not verified' in c['evidence'] for c in cs)

def test_long_anchor_falls_back_to_domain():
    cs, _ = discover.extract_candidates('<a href="https://acme.io">This is a very long anchor text that keeps going well past sixty characters total here</a>', 'x.co')
    assert cs[0]['company'] == 'Acme'
