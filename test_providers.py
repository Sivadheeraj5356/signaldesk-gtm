import providers

CFG = dict(industry='SaaS', region='India', offer='Payroll automation', company_details='B2B payroll software for 10-200 person companies',
           company_name='Acme', company_website='', linkedin='', threshold=55, min_size=10, max_size=500, cta='', ai=False, channel='email')

def test_query_building_from_profile():
    qs = providers.build_icp_queries(CFG)
    assert qs and all(isinstance(q, str) and len(q) > 3 for q in qs)
    joined = ' '.join(qs).lower()
    assert 'payroll' in joined  # keywords from company_details drive queries
    assert len(qs) <= 4

def test_query_building_empty_profile():
    assert providers.build_icp_queries(dict(industry='', region='', offer='', company_details='')) == []

def test_wiki_parse_joins_official_sites():
    search = {'query': {'search': [{'title': 'Gusto, Inc.'}, {'title': 'Payroll'}]}}
    entities = {'entities': {
        'Q1': {'sitelinks': {'enwiki': {'title': 'Gusto, Inc.'}},
               'claims': {'P856': [{'mainsnak': {'datavalue': {'value': 'https://gusto.com/'}}}]}},
        'Q2': {'sitelinks': {'enwiki': {'title': 'Payroll'}}, 'claims': {}},
    }}
    cs = providers.wiki_parse_results(search, entities, 'payroll software company')
    assert len(cs) == 1
    c = cs[0]
    assert c['company'] == 'Gusto' and c['domain'] == 'gusto.com'
    assert c['provider'] == 'wikipedia' and c['provider_query'] == 'payroll software company'
    assert c['source'].startswith('https://en.wikipedia.org/wiki/') and c['status'] == 'unverified'

def test_hn_parse_filters_and_provenance():
    hits = {'hits': [
        {'title': 'Rippling raises round', 'url': 'https://rippling.com/blog/news', 'objectID': '123'},
        {'title': 'Show HN thread', 'url': 'https://github.com/foo/bar', 'objectID': '124'},
        {'title': 'No url hit', 'objectID': '125'},
    ]}
    cs = providers.hn_parse_results(hits, 'payroll saas')
    assert len(cs) == 1
    assert cs[0]['domain'] == 'rippling.com'
    assert cs[0]['source'] == 'https://news.ycombinator.com/item?id=123'
    assert cs[0]['status'] == 'unverified'

def test_brave_not_configured_without_key(monkeypatch):
    monkeypatch.delenv('SIGNALDESK_BRAVE_API_KEY', raising=False)
    assert providers.brave_candidates('anything') == 'not_configured'
