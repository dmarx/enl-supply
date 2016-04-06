from py2neo import Graph, Node, Relationship, authenticate
from passlib.hash import bcrypt
from datetime import datetime
import os
import uuid
#import sqlite3 # Create a separate database to track TTL
# You know what, I'll implement TTL later.

# The way I'm building this, every attribute on the node is going to require a
# a new HTTP request. Would probably be better if I had a mechanism to set a 
# bunch of attributes at once and then push them, like committing a transaction.
# No rush, implement that later.

# I feel like I'd rather have these in a configuration file, but whatever. We
# can look for them in environment variables too. No problem.
url = os.environ.get('GRAPHENEDB_URL', 'http://localhost:7474') # GrapheneDB is Heroku's Neo4j as a service
username = os.environ.get('NEO4J_USERNAME', 'neo4j')
password = os.environ.get('NEO4J_PASSWORD', 'dev_p4ss') # Need to change password to use authentication neoauth neo4j neo4j dev_p4ss

if username and password:
    authenticate(url.strip('http://'), username, password)

graph = Graph(url + '/db/data/')

class SimpleNode(object):
    def __init__(self, pk=None):
        self.pk = pk
        if not pk:
            self.pk = self.new_guid()
        self.pk_name = 'id'
    @property
    def nodetype(self):
        return str(self.__class__).split('.')[-1][:-2]
    def find(self):
        node = graph.find_one(self.nodetype, self.pk_name, self.pk)
        return node
    @staticmethod
    def new_guid():
        return ''.join(str(uuid.uuid4()).split('-'))
    @staticmethod
    def timestamp():
        epoch = datetime.utcfromtimestamp(0)
        now = datetime.now()
        delta = now - epoch
        return delta.total_seconds()
    @property
    def node(self):
        if not hasattr(self, '_node'):
            self._node = self.find()
        return self._node
    def refresh(self):
        self._node = self.find()
        #graph.pull(self._node)
    #def push(self):
    #    graph.push(self.node)

class User(SimpleNode):
    def __init__(self, username):
        self.displayname = username
        self.username = username.lower()
        self.pk_name = "username"
        self.inventory = Inventory(username)
    # This is necessary to make sure inherited functions don't break
    @property
    def pk(self):
        return self.username
    
    def register(self, password):
        user = graph.merge_one("User", "username", self.username)
        if not user['password']:
            user['displayname'] = self.displayname
            user['password'] = bcrypt.encrypt(password)
            graph.push(user)
            self._node = user
            return True
        return False
        
    def verify_password(self, password):
        if self.node:
            return bcrypt.verify(password, self.node['password'])
        else:
            return False

    @property
    def is_active(self):
        if self.node:
            return self.node['active'] # None if not set
            
    def activate(self):
        self.node['active'] = True
        graph.push(self._node)
        
    def deactivate(self):
        self.node['active'] = False
        graph.push(self._node)
        
    def set_user_relationship(self, target, source=None, cost=3, verified=True, override=False):
        if not source:
            source=self.node
        if not type(source) == Node:
            source = graph.merge_one("User", "username", source)
        if not type(target) == Node:
            target = graph.merge_one("User", "username", target)    
        rel = graph.match_one(source, "CAN_REACH", target)
        if rel is None:
            rel=[] # this shouldn't be necessary...
        if len(list(rel)) > 0 and override: # via http://stackoverflow.com/questions/26747441/py2neo-how-to-check-if-a-relationship-exists
            rel['cost'] = cost
            rel['verified'] = verified
            graph.push(rel)
        else:
            rel = Relationship(source, "CAN_REACH", target, cost=cost, verified=verified)
            graph.create_unique(rel) # Do I need to enforce a uniqueness constraint on relationships?
        
    def add_verified_relationship(self, user, cost=None, default_cost=3):
        """
        Creates a relationship to the target user with a given cost and sets it as 
        "verified." Additionally, if the reverse relationsihp does not exist, 
        creates an unverified relationship with default cost in the opposite 
        direction. This is to give each user the flexibility to define for themselves
        how easy or hard it is to meet with a given player. 
        
        If I abandon this user-specific cost, I'd only need half the storage space for edges.
        """
        if cost is None:
            cost = default_cost
        self.set_user_relationship(source=self.node, target=user, cost=cost, verified=True, override=True)
        self.set_user_relationship(source=user, target=self.node, cost=default_cost, verified=False, override=False)
        
    def add_community_membership(self, community):
        comm = graph.merge_one("Community", "name", community)   
        rel  = Relationship(self.node, "IS_MEMBER_OF", comm)
        graph.create_unique(rel)
        
    # Can I generalize this?
    def neighbors(self, radius=1):
        query = """
        MATCH (user:User)-[path:CAN_REACH*1..{radius}]-(neighbor:User)
        WHERE user.username = {{username}}
        RETURN neighbor, path
        """.format(radius=radius)
        return graph.cypher.execute(query, username=self.username)
        
    def verified_neighbors(self):
        query = """
        MATCH (user:User)-[path:CAN_REACH]-(neighbor:User)
        WHERE user.username = {username}
        AND path.verified = TRUE
        RETURN neighbor, path
        """
        return graph.cypher.execute(query, username=self.username)
        
    def unverified_neighbors(self):
        query = """
        MATCH (user:User)-[r:CAN_REACH]-(b:User)
        WHERE user.username = {username}
        AND r.verified = FALSE
        RETURN b, r
        """
        return graph.cypher.execute(query, username=self.username)
        
    def suggest_neighbors_by_community(self, limit):
        query="""
        MATCH (user:User)-[r:IS_MEMBER_OF]->(community:Community)<-[r:IS_MEMBER_OF]-(suggestion:User)
        WHERE user.username = {username}
        AND NOT (user)-[:CAN_REACH]-(suggestion)
        RETURN suggestion, COLLECT(community.name), COUNT(*) as N
        ORDER BY N DESC LIMIT {k}
        """
        # Not sure COUNT(*) is doing what I think it is, need to test more
        return graph.cypher.execute(query, username=self.username, k=limit)
        
    def communities(self):
        query = """
        MATCH (user:User)-[r:IS_MEMBER_OF]->(b:Community)
        WHERE user.username = {username}
        RETURN b, r
        """
        return graph.cypher.execute(query, username=self.username)

    def supply_paths(self, radius=2, direction='in'):
        """Paths that fulfill this user's inventory demands to within a given radius"""
        
        # We need to find all paths between the current node and any given candidate
        # target, and filter down to those with the shortest possible cost
        s1={'in':'<', 'out':''}[direction]
        s2={'in':'', 'out':'>'}[direction]
        s3={'in':'<', 'out':'>'}[direction]
        query="""
        MATCH (demand)<-[:HAS]-(a){s1}-[chain:CAN_REACH*1..{radius}]-{s2}(terminus)-[:HAS]-(supply) 
        where a.username={{username}}
        and supply.type = demand.type 
        and SIGN(demand.value) {s3} SIGN(supply.value) 
        return terminus, min(reduce(tot=0, r in chain | tot + r.cost)) AS minCost
        """.format(s1=s1, s2=s2, s3=s3, radius=radius)
        min_path_cost = graph.cypher.execute(query, username=self.username)
        
        query="""
        MATCH (demand)<-[:HAS]-(a){s1}-[chain:CAN_REACH*1..{radius}]-{s2}(terminus)-[:HAS]-(supply) 
        where a.username={{username}}
        and supply.type = demand.type 
        and SIGN(demand.value) {s3} SIGN(supply.value)  
        RETURN terminus, chain, supply, reduce(tot=0, r in chain | tot + r.cost) as totCost
        ORDER BY totCost
        """.format(s1=s1, s2=s2, s3=s3, radius=radius)
        paths = graph.cypher.execute(query, username=self.username)
        
        source_costs = dict((rec.terminus['username'], rec.minCost) for rec in min_path_cost)

        return self._filter_paths(paths, source_costs, direction)
        
    def _filter_paths(self, paths, source_costs, direction):
        """ filter paths down to paths with the least weight between two nodes in the event
        that several paths with the same source and target are returned.
        """
        best_paths = []
        for rec in paths:
            if rec.totCost == source_costs[rec.terminus['username']]:
                best_paths.append(rec)
                
        # Expand the 'chain'
        supply_chains = []
        for rec in best_paths:
            path = []
            for rel in rec.chain:
                #path.extend(rel.nodes)
                if direction == 'in':
                    q,p = rel.nodes
                else:
                    p,q = rel.nodes
                if not path:
                    path =[p,q]
                else:
                    path.append(q)
                
            supply_chains.append({'path':path, 'supply':rec.supply, 
                                  'terminus':rec.terminus, 'cost':rec.totCost})
        
        return supply_chains, best_paths
        
#I'm pretty sure there's a better way I could implement this on the python side.
# Feels fine on the database side, but the class api smells funny.
class Inventory(SimpleNode):
    types =  ['xmp', # XMP
              'res', # Resonator
              'fa',  # Force Amp
              'tur', # Turret
              'us',  # Ultra Strike
              'sh']  # Shield
    
    def __init__(self, username):
        self.username = username
        self.usernode = graph.find_one('User', 'username', username)
    
    def find(self):
        query = """
        MATCH (user:User)-[r:HAS]->(b:Inventory)
        WHERE user.username = {username}
        RETURN b
        """
        d={}
        results = graph.cypher.execute(query, username=self.username)
        for record in results:
            node = record[0]
            d[(node['type'], node['level'])] = node
        return d
    
    @property
    def nodes(self):
        return self.node
        
    def set(self, type, value, level=None):
        if value=='0':
            self.delete(type, level)
            return
        self.find() # Make sure relevant node in dictionary hasn't been deleted?
        k = (type,level)
        if self.nodes.has_key(k):
            node = self.nodes[k]
            node['value'] = value
            graph.push(node)
        else:
            node = Node('Inventory',type=type,value=value,level=level,id=self.new_guid())
            self.nodes[k] = node
            graph.create(Relationship(self.usernode,'HAS',node))
    
    def delete(self, type, level=None):
        k = (type,level)
        if self.nodes.has_key(k):
            node = self.nodes.pop(k)
        query = """
        MATCH (n:Inventory)<-[:HAS]-(u:User)
        WHERE u.username = {username}
        AND   n.type = {type}
        AND   n.level = {level}
        DETACH DELETE n
        """
        graph.cypher.execute(query, username=self.username, type=type, level=level)
        
        
if __name__ == '__main__':
    # These are basically all tests and should be handled by nose. I'll port this later.
    pwd = 'fakepass'
    user = User('scratchscratch')
    user.register(pwd)
    #user.verify_password(pwd)
    #user.is_active
    #user.activate()
    #user.is_active
    #user.deactivate()
    #user.is_active
    
    user.add_verified_relationship('msdaphne', cost=1)
    user.inventory.set(type='xmp', level=8, value=100)