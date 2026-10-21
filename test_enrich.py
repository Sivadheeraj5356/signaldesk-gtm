import enrich

SAMPLE = '''<html><body>
<a href="mailto:hello@acme.com">Contact us</a>
<a href="mailto:priya.sharma@acme.com">Priya</a>
<a href="tel:+1-415-555-0132">Call</a>
<a href="https://www.linkedin.com/company/acme/">LinkedIn</a>
<a href="https://linkedin.com/in/priyasharma?utm_source=site">Priya on LinkedIn</a>
<p>Reach us at sales@acme.com for quotes.</p>
<script>var x="noreply@tracker.example";</script>
<img src="x@2x.png">
<a href="mailto:example@example.com">placeholder</a>
</body></html>'''

def test_extract_published_contacts():
    cs = enrich.extract_contacts(SAMPLE, 'https://acme.com/contact')
    byv = {(c['type'], c['value']): c for c in cs}
    assert ('email', 'hello@acme.com') in byv
    assert byv[('email', 'hello@acme.com')]['label'] == 'generic'
    assert byv[('email', 'priya.sharma@acme.com')]['label'] == 'personal'
    assert ('phone', '+1-415-555-0132') in byv
    assert ('linkedin', 'https://www.linkedin.com/company/acme') in byv
    assert byv[('linkedin', 'https://www.linkedin.com/company/acme')]['label'] == 'company'
    assert ('linkedin', 'https://linkedin.com/in/priyasharma') in byv
    assert ('email', 'sales@acme.com') in byv
    # placeholders and script contents excluded
    assert not any('example.com' in c['value'] for c in cs)
    assert not any('tracker' in c['value'] for c in cs)
    assert not any('2x.png' in c['value'] for c in cs)
    # every contact carries source + status
    assert all(c['status'] == 'published' and c['source_url'] == 'https://acme.com/contact' for c in cs)

def test_dedupe_and_phone_bounds():
    html = '<a href="mailto:a@b.co">x</a><p>a@b.co</p><a href="tel:123">bad</a><a href="tel:+919876543210">ok</a>'
    cs = enrich.extract_contacts(html, 'https://b.co/')
    emails = [c for c in cs if c['type'] == 'email']
    assert len(emails) == 1
    phones = [c['value'] for c in cs if c['type'] == 'phone']
    assert phones == ['+919876543210']

def test_empty_page():
    assert enrich.extract_contacts('<html><body><p>No contacts</p></body></html>', 'https://x.co/') == []
