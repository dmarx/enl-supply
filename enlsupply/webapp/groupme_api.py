import requests
#from utilities import verify_agent
from collections import defaultdict

class GroupmeUser(object):
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
        data = self._request('/groups')
        if data:
            groups_members = {}
            members_groups = defaultdict(list)
            neighbors_nicks = {}
            ids = set()
            for g in data:
                members = []
                for user in g['members']:
                    id = user['user_id']
                    members.append(id)
                    members_groups[id].append(g['name'])
                    neighbors_nicks[id] = user['nickname']
                    ids.add(id)
                groups_members[g['name']] = members
        self.groups_members = groups_members
        self.members_groups = members_groups
        self.neighbors_nicks = neighbors_nicks
        #self.neighbors_names = self.map_ids_to_agents(ids)
        # I don't need to convert GM nicknames to agent names until after
        # the user specifies which agents/groups they want to use to populate
        # the graph.
    def map_ids_to_agents(self, ids):
        d = {}
        for id in ids:
            # Before hitting enl.io, we should probably check our database to
            # reduce the number of requests we're throwing at them.
            # Should I keep a separate database and/or attach to the graph as a
            # node attribute? I think i shold probably at least attach to the graph. 
            # I guess the question is if I should keep a separate database 
            # mapping agent names to gm ids.
            d[id] = verify_agent(id, self.app_token, service='groupme')
        return d
    def similar_users(self,k=10):
        if not hasattr(self, 'members_groups'):
            self.get_groups()
        return sorted(self.members_groups.iteritems(), key=lambda x: -len(x[1]))[1:k]
            
if __name__ == '__main__':
    demo_token = None
    app_token = None
    #user = GroupmeUser(demo_token, app_token)
    #user.similar_users(20)