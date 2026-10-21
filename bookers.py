"""Meeting booking provider contracts.

'link' mode (default) embeds the workspace owner's own scheduling link in the
meeting request draft; the recipient books themselves. 'calcom' can check
availability and create bookings through the Cal.com API once the operator sets
SIGNALDESK_CALCOM_API_KEY; creating a real booking additionally requires the
campaign's operational approval. All network paths support dry_run.
"""
import os, json, urllib.request

def provider_state():
    return {
        'link': dict(configured=True, note='The recipient books through your own scheduling link. No API needed.'),
        'calcom': dict(configured=bool(os.environ.get('SIGNALDESK_CALCOM_API_KEY')),
                       note='Cal.com API. Operator sets SIGNALDESK_CALCOM_API_KEY.'),
    }

def availability(event_type_id, date, dry_run=True, timeout=30):
    key = os.environ.get('SIGNALDESK_CALCOM_API_KEY')
    if not key: raise ValueError('calcom provider is not configured: missing SIGNALDESK_CALCOM_API_KEY')
    url = 'https://api.cal.com/v1/slots?eventTypeId=' + str(int(event_type_id)) + '&date=' + str(date)
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key})
    if dry_run:
        return dict(provider='calcom', dry_run=True, request=dict(url=url, method='GET'),
                    note='Dry run: this availability check was not performed')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, slots=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com availability check failed: ' + str(e)[:200].replace(key, ''))

def book(event_type_id, start, invitee_name, invitee_email, dry_run=True, timeout=30):
    key = os.environ.get('SIGNALDESK_CALCOM_API_KEY')
    if not key: raise ValueError('calcom provider is not configured: missing SIGNALDESK_CALCOM_API_KEY')
    payload = json.dumps({'eventTypeId': int(event_type_id), 'start': start,
                          'responses': {'name': invitee_name[:200], 'email': invitee_email[:200]},
                          'timeZone': 'Asia/Calcutta', 'language': 'en'}).encode()
    req = urllib.request.Request('https://api.cal.com/v1/bookings', data=payload,
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    if dry_run:
        return dict(provider='calcom', dry_run=True, request=dict(url=req.full_url, method='POST',
                    event_type_id=int(event_type_id), start=start, invitee=invitee_email),
                    note='Dry run: this booking was not created')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(provider='calcom', dry_run=False, booking=json.loads(r.read(500000)))
    except Exception as e:
        raise ValueError('Cal.com booking failed: ' + str(e)[:200].replace(key, ''))
