import requests
from collections import defaultdict 
import time # for dm guid
try:
    import ujson as json
except:
    import json

class GroupmeUser(object):
    jarvis_id = '15678427'
    def __init__(self, user_token, app_token=None):
        self.user_token = user_token
        self.app_token  = app_token
        self.api = 'https://api.groupme.com/v3{endpoint}'
    def _request(self, endpoint, **kwargs):
        url = self.api.format(endpoint=endpoint)
        payload = {'token':self.user_token}
        payload.update(kwargs)
        response = requests.get(url, params=payload)
        if response.status_code == 200:
            return response.json()['response']
    @property
    def id(self):
        if not hasattr(self, '_id'):
            self._get_me()
        return self._id
    @property
    def nickname(self):
        if not hasattr(self, '_id'):
            self._get_me()
        return self._nickname
    def _get_me(self):
        data = self._request('/users/me')
        self._id = data['user_id']
        self._nickname = data['name']
    def get_groups(self):
        # object to generate:
        # * Dict mapping groups to a list of userids/nicknames
        # * a set of ids to be converted to agent names
        # * A dict mapping agent names to their groups
        data = self._request('/groups') # I don't know why there wouldn't be data...
        groups_members = {}
        members_groups = defaultdict(list)
        neighbors_nicks = defaultdict(set)
        if data:
            ids = set()
            for g in data:
                members = []
                for user in g['members']:
                    id = user['user_id']
                    members.append(id)
                # If Roland Jarvis is not in a group, it's not managed by enl.io 
                # and we should ignore the whole group to ensure we are only
                # suggesting ingress (enl) agents.
                if self.jarvis_id not in members:
                    continue
                for user in g['members']:
                    id = user['user_id']
                    members_groups[id].append(g['name'])
                    neighbors_nicks[id].add(user['nickname'])
                    ids.add(id)
                members.sort()
                groups_members[g['name']] = members
        for k,v in neighbors_nicks.iteritems():
            neighbors_nicks[k] = list(v)
            neighbors_nicks[k].sort()
        self.groups_members = groups_members
        self.members_groups = members_groups
        self.neighbors_nicks = neighbors_nicks
    def similar_users(self,k=10):
        if not hasattr(self, 'members_groups'):
            self.get_groups()
        if k==0:
            k=len(self.members_groups)
        k=k+2
        sugg = sorted(self.members_groups.iteritems(), key=lambda x: -len(x[1]))[1:k]
        print type(self.id), self.id
        return [{'nickname':self.neighbors_nicks[id], 
                 'n_groups':len(groups),
                 'groups':groups,
                 'id':id
                 } for id, groups in sugg 
                 if id not in (self.jarvis_id,self.id)]
    
    def direct_message(self, 
                        groupme_id, 
                        text="Hello!"
                        ):
        api_url = 'https://api.groupme.com/v3'
        endpoint = '/direct_messages'
        url = api_url+endpoint
        
        access_token = self.user_token
        guid = str(time.time()) + 'enl.supply_message'

        payload = json.dumps(
                    {'direct_message':
                        {'source_guid':guid,
                        'recipient_id':str(groupme_id),
                        'text':text
                        }
                    })

        response = requests.post(url, 
                                 params={'token':access_token}, 
                                 data=payload,
                                 headers={'content-type': 'application/json'})
        return response

if __name__ == '__main__':
    demo_token = None
    app_token = None
    #user = GroupmeUser(demo_token, app_token)
    #user.similar_users(20)