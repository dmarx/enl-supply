import requests

def verify_agent(id, token, service='groupme'):
    """
    Use the enl.io API to validate an agent by their groupme id and return their 
    agent name.
    """
    payload={'id':id, 'token':token, 'service':service}
    r = requests.get('https://enl.io/api/whois', params=payload)
    if r.text:
        return r.json()['agent_name']
    
    
    