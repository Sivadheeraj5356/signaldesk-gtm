"""Meeting booking provider contracts.

Binding rules: the invitee is the enrolled member's bound contact (name + email
evidence on the account), the slot is an explicit ISO start with an explicit
IANA timezone, and real bookings additionally require the campaign's
operational approval plus a configured provider FOR THIS WORKSPACE (env key is
owner-only). 'link' mode stays the default: the recipient books themselves
through the owner's own scheduling link.
"""
import os, json, urllib.request

def provider_state(ws='owner'):
    cal_env = bool(os.environ.get('SIGNALDESK_CALCOM_API_KEY'))
    return {
        'link': dict(configured=True, note='The recipient books through your own scheduling link. No API needed.'),
        'calcom': dict(configured=(ws == 'owner') and cal_env,
                       note='Cal.com API. Owner workspace: operator env key (development path). Tenant workspaces need their own connection, which is not built yet.' if cal_env else 'Cal.com API. Not connected.'),
    }

def availability(event_type_id, date, ws='owner', dry_run=True, timeout=30):
    key = os.environ.get('SIGNALDESK_CALCOM_API_KEY')
    if not key or ws != 'owner':
        raise ValueError('calcom provider is not configured for this workspace (tenant connections are not built yet)')
    url = 'https://api.cal.com/v1/slots?eventTypeId=' + str(int(event_type_id)) + '&date=' + str(date)
    if dry_run:
        return dict(provider='calcom', dry_run=True, request=dict(url=url, method='GET'),
                    note='Dry run: this availability check was not performed')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, slots=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com availability check failed: ' + str(e)[:200].replace(key, ''))

def book(event_type_id, start, timezone, invitee_name, invitee_email, ws='owner', dry_run=True, timeout=30):
    key = os.environ.get('SIGNALDESK_CALCOM_API_KEY')
    if not key or ws != 'owner':
        raise ValueError('calcom provider is not configured for this workspace (tenant connections are not built yet)')
    payload = json.dumps({'eventTypeId': int(event_type_id), 'start': start,
                          'responses': {'name': invitee_name[:200], 'email': invitee_email[:200]},
                          'timeZone': timezone, 'language': 'en'}).encode()
    if dry_run:
        return dict(provider='calcom', dry_run=True,
                    request=dict(url='https://api.cal.com/v1/bookings', method='POST',
                                 event_type_id=int(event_type_id), start=start, timezone=timezone, invitee=invitee_email),
                    note='Dry run: this booking was not created')
    req = urllib.request.Request('https://api.cal.com/v1/bookings', data=payload,
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, booking=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com booking failed: ' + str(e)[:200].replace(key, ''))
