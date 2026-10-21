"""Meeting booking provider contracts (Cal.com API v2 shapes, verified against
cal.com/docs/api-reference/v2 on 2026-10-22).

Binding rules: the invitee is the enrolled member's bound contact (name + email
evidence on the account), the slot is an explicit ISO start with an explicit
IANA timezone, and real bookings additionally require the campaign's
operational approval plus a configured provider FOR THIS WORKSPACE (env key is
owner-only). 'link' mode stays the default: the recipient books themselves
through the owner's own scheduling link.
"""
import os, json, urllib.request

API_VERSION = '2024-09-04'  # cal-api-version header pin; bump deliberately

def provider_state(ws='owner'):
    cal_env = bool(os.environ.get('SIGNALDESK_CALCOM_API_KEY'))
    return {
        'link': dict(configured=True, note='The recipient books through your own scheduling link. No API needed.'),
        'calcom': dict(configured=(ws == 'owner') and cal_env,
                       note='Cal.com API v2. Owner workspace: operator env key (development path). Tenant workspaces need their own connection, which is not built yet.' if cal_env else 'Cal.com API v2. Not connected.'),
    }

def _key(ws):
    key = os.environ.get('SIGNALDESK_CALCOM_API_KEY')
    if not key or ws != 'owner':
        raise ValueError('calcom provider is not configured for this workspace (tenant connections are not built yet)')
    return key

def availability(event_type_id, start_date, end_date, timezone='UTC', ws='owner', dry_run=True, timeout=30):
    key = _key(ws)
    url = ('https://api.cal.com/v2/slots?eventTypeId=' + str(int(event_type_id))
           + '&start=' + str(start_date) + '&end=' + str(end_date)
           + '&timeZone=' + urllib.parse.quote(timezone, safe=''))
    if dry_run:
        return dict(provider='calcom', dry_run=True,
                    request=dict(url=url, method='GET', headers=['cal-api-version: ' + API_VERSION]),
                    note='Dry run: this availability check was not performed')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'cal-api-version': API_VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, slots=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com availability check failed: ' + str(e)[:200].replace(key, ''))

def book(event_type_id, start, timezone, invitee_name, invitee_email, ws='owner', dry_run=True, timeout=30):
    key = _key(ws)
    payload = json.dumps({'eventTypeId': int(event_type_id), 'start': start,
                          'attendee': {'name': invitee_name[:200], 'email': invitee_email[:200],
                                       'timeZone': timezone, 'language': 'en'}}).encode()
    if dry_run:
        return dict(provider='calcom', dry_run=True,
                    request=dict(url='https://api.cal.com/v2/bookings', method='POST',
                                 headers=['cal-api-version: ' + API_VERSION],
                                 event_type_id=int(event_type_id), start=start, timezone=timezone, invitee=invitee_email),
                    note='Dry run: this booking was not created')
    req = urllib.request.Request('https://api.cal.com/v2/bookings', data=payload,
                                 headers={'Authorization': 'Bearer ' + key, 'cal-api-version': API_VERSION,
                                          'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, booking=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com booking failed: ' + str(e)[:200].replace(key, ''))
