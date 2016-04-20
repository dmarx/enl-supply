from py2neo import Graph, Node, Relationship, authenticate
from datetime import datetime
import os
import uuid
from groupme_api import GroupmeUser
from collections import OrderedDict, defaultdict
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
        print self.nodetype, self.pk_name, self.pk
        node = graph.find_one(self.nodetype, self.pk_name, self.pk)
        print type(node)
        return node
    def merge(self):
        return graph.merge_one(self.nodetype, self.pk_name, self.pk)
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
    def __init__(self, groupme_id, groupme_nick=None, agent_name=None):
        # For inherited methods, in particular .find()
        
        self.agent_name = agent_name
        #self.groupme_nick = groupme_nick
        self.groupme_id = groupme_id
        
        self.pk_name = "groupme_id"
        self.pk = self.groupme_id
        
        user = self.merge()
        if agent_name and not user['agent_name']:
            user['agent_name'] = agent_name
        self.agent_name = user['agent_name']
        #if groupme_nick and not not user['groupme_nick']:
        #    user['groupme_nick'] = groupme_nick
        graph.push(user)
        self._node = user
        self.inventory = Inventory(self.pk, self.pk_name)
        
    @property
    def display_name(self):
        if self.agent_name:
            return self.agent_name
        else:
            return self.groupme_nick

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
        
    def disconnect(self, groupme_id=None, agent_name=None, target=None):
        source = self.node
        if not target:
            assert(groupme_id or agent_name)
            if groupme_id:
                target = graph.merge_one("User", "groupme_id", groupme_id)
            else:
                target = graph.merge_one("User", "agent_name", agent_name)
            
        rel_out = graph.match(source, "CAN_REACH", target).next()
        rel_in  = graph.match(target, "CAN_REACH", source).next()
        #rel_out = graph.match_one(source, "CAN_REACH", target)
        #rel_in  = graph.match_one(target, "CAN_REACH", source)
        
        # If rel_in is verified, unverify rel_out and enforce cost parity.
        # If rel_in is not verified, delete both relationships.
        
        if rel_in['verified']:
            rel_out['verified'] = False
            rel_out['cost'] = rel_in['cost']
            graph.push(rel_out)
        else:
            graph.delete(rel_out)
            graph.delete(rel_in)
            agg_rel = graph.match_one(source, "IS_CONNECTED", target)
            graph.delete(agg_rel)
        
    def block(self, groupme_id=None, agent_name=None, target=None):
        """
        Unverify outgoing CAN_REACH relationship and prevent any exchange 
        suggestions that include this edge in the path.
        """
        source = self.node
        if not target:
            assert(groupme_id or agent_name)
            if groupme_id:
                target = graph.merge_one("User", "groupme_id", groupme_id)
            else:
                target = graph.merge_one("User", "agent_name", agent_name)
            
        # 1. Create block relationship
        block = Relationship(source, "BLOCK", target)
        graph.create_unique(block) # Do I need to enforce a uniqueness constraint on relationships?
        
        # 2. Set outgoing CAN_REACH to "verified=False" if the verified relationship already exists
        rel = graph.match_one(source, "CAN_REACH", target)
        if rel['verified']:
            rel['verified'] = False
            graph.push(rel)
        
        # This is a sort of redundant database request. Can probably be factored out.
        #if self.is_neighbor(agent_name=target['agent_name']): 
        #    self.disconnect(target=target)
        self.disconnect(target=target)
            
        a,b = block.nodes
        if a['agent_name'] < b['agent_name']:
            self.update_aggregate_path(target, block1=block)
        else:
            self.update_aggregate_path(target, block2=block)
            
    def unblock(self, groupme_id=None, agent_name=None, target=None):
        # The code to bind the target node should probably be factored out to DRY out the class some
        # ... I shold just use the pk/pk_name idiom I use for the rest of the class.
        source = self.node
        if not target:
            assert(groupme_id or agent_name)
            if groupme_id:
                target = graph.merge_one("User", "groupme_id", groupme_id)
            else:
                target = graph.merge_one("User", "agent_name", agent_name)
                
        block = graph.match(source, "BLOCK", target)
        block_l = list(block)
        if len(block_l)>0:
            # There should only ever be one, but we can loop anyway just to be safe.
            for block in block_l:
                graph.delete(block)
        
        self.update_aggregate_path(target) # We only need to update the blocked attribute, not the cost or verified.
        
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
        return rel
            
    def modify_verified_relationship(self, groupme_id, cost):
        source = self.node
        target = graph.merge_one("User", "groupme_id", groupme_id)
        rel1 = self.set_user_relationship(source=source, target=target, cost=cost, verified=True, override=True)
        
        rel2 = graph.match_one(target, "CAN_REACH", source)
        if not rel2['verified']:
            rel2 = self.set_user_relationship(source=target, target=source, cost=cost, verified=rel2['verified'], override=True)
            
        self.update_aggregate_path(target, r1=rel1, r2=rel2)
            
    def add_verified_relationship(self, groupme_id, agent_name=None, cost=None, default_cost=3):
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
        neighbor = graph.merge_one("User", 'groupme_id', groupme_id)
        if agent_name and not neighbor['agent_name']:
            neighbor['agent_name'] = agent_name
            graph.push(neighbor)
        r1 =self.set_user_relationship(source=self.node, target=neighbor, cost=cost, verified=True, override=True)
        r2 = self.set_user_relationship(source=neighbor, target=self.node, cost=default_cost, verified=False, override=False)
        self.unblock(target=neighbor)
        
        self.update_aggregate_path(target=neighbor, r1=r1, r2=r2)
        
    def update_aggregate_path(self, target, r1=None, r2=None, block1=None, block2=None):
        """
        If only one of r1/r2 provided, assumes r1: src.agent_name < tgt.agent_name 
        and r2: src.agent_name > tgt.agent_name. Same if only one of block1/block2
        provided.
        """
        # This function is probably overkill. For most cases, we can probably do a more targetted
        # update, i.e. of either the cost, verified, or blocked parameter (depending on what was
        # changed). Each graph.match_one call is another database request, so we can potentially
        # speed up the app (and maybe make hosting cheaper) by reducing database i/o.
        
        # Add aggregate path
        source = self.node
        if source['agent_name'] >  target['agent_name']:
            source, target = target, source
        
        create=False
        agg_rel = graph.match_one(source, "IS_CONNECTED", target)
        if not agg_rel:
            create = True
            agg_rel = Relationship(source, "IS_CONNECTED", target)
        
        block1 = graph.match(source, "BLOCK", target)
        block2 = graph.match(target, "BLOCK", source)
        agg_rel['blocked'] = len(list(block1)) + len(list(block2)) > 0
        
        if not r1:
            r1 = graph.match_one(source, 'CAN_REACH', target)
        if not r2:
            r2 = graph.match_one(target, 'CAN_REACH', source)
        
        if r1 and r2:
            agg_rel['max_cost'] = max(r1['cost'], r2['cost'])
            agg_rel['min_cost'] = min(r1['cost'], r2['cost'])
            agg_rel['double_verified'] = r1['verified'] and r2['verified']
        
        if create:
            graph.create_unique(agg_rel)
        else:
            graph.push(agg_rel)
            
        print "AGGREL"
        print agg_rel
        
    def add_community_membership(self, community):
        comm = graph.merge_one("Community", "name", community)   
        rel  = Relationship(self.node, "IS_MEMBER_OF", comm)
        graph.create_unique(rel)
        
    # Can I generalize this?
    def neighbors(self, radius=1):
        query = """
        MATCH (user:User)-[path:CAN_REACH*1..{radius}]-(neighbor:User)
        WHERE user.{pk_name} = {{{pk_name}}}
        RETURN neighbor, path
        """.format(radius=radius, pk_name=self.pk_name)
        return graph.cypher.execute(query, {self.pk_name:self.pk})
        
    def verified_neighbors(self):
        query = """
        MATCH (user:User)-[path:CAN_REACH]->(neighbor:User)
        WHERE user.{pk_name} = {{{pk_name}}}
        AND path.verified = TRUE
        RETURN neighbor, path
        """.format(pk_name=self.pk_name)
        return graph.cypher.execute(query, {self.pk_name:self.pk})
        
    def unverified_neighbors(self):
        query = """
        MATCH (user:User)-[path:CAN_REACH]->(neighbor:User)
        WHERE user.{pk_name} = {{{pk_name}}}
        AND path.verified = FALSE
        RETURN neighbor, path
        """.format(pk_name=self.pk_name)
        return graph.cypher.execute(query, {self.pk_name:self.pk})
        
    def unverified_neighbors_similarity(self):
        # Samea s above but returns a similarity score
        query = """
        MATCH (user:User)-[path:CAN_REACH]->(neighbor:User)
        WHERE user.{pk_name} = {{{pk_name}}}
        AND path.verified = FALSE
        WITH user, neighbor, path
            MATCH (x)-[r*1..2]-(y)
            WHERE x=user AND y=neighbor
        RETURN neighbor, 
               size(r) AS sim, 
               size([r0 in r WHERE r0.verified]) AS sim_verified
        ORDER BY sim DESC, sim_verified DESC
        """.format(pk_name=self.pk_name)
        return graph.cypher.execute(query, {self.pk_name:self.pk})
        
    def suggest_neighbors_by_community(self, limit):
        query="""
        MATCH (user:User)-[r:IS_MEMBER_OF]->(community:Community)<-[r:IS_MEMBER_OF]-(suggestion:User)
        WHERE user.{pk_name} = {{{pk_name}}}
        AND NOT (user)-[:CAN_REACH]-(suggestion)
        RETURN suggestion, COLLECT(community.name), COUNT(*) as N
        ORDER BY N DESC LIMIT {k}
        """.format(pk_name=self.pk_name)
        # Not sure COUNT(*) is doing what I think it is, need to test more
        return graph.cypher.execute(query, {self.pk_name:self.pk, 'k':limit})
        
    def is_neighbor(self, agent_name=None, groupme_id=None):
        if agent_name:
            return self._is_neighbor_agentname(agent_name)
        if groupme_id:
            return self._is_neighbor_groupme(groupme_id)
    
    def _is_neighbor_agentname(self, agent_name):
        query="""
        OPTIONAL MATCH (a)-[r:CAN_REACH]-(b)
        WHERE a.agent_name = {src_name}
        AND   b.agent_name = {tgt_name}
        RETURN r IS NOT NULL AS is_neighbor
        """
        return graph.cypher.execute(query, 
            {'src_name':self.agent_name, 'tgt_name':agent_name}
            )[0].is_neighbor
    
    def _is_neighbor_groupme(self, groupme_id):
        raise Exception('User._is_neighbor_groupme not Implemented')
        pass
        
        
    def communities(self):
        query = """
        MATCH (user:User)-[r:IS_MEMBER_OF]->(b:Community)
        WHERE user.username = {username}
        RETURN b, r
        """
        return graph.cypher.execute(query, username=self.username)

    def supply_paths(self, radius=2, direction='in'):
        """Paths that fulfill this user's inventory demands to within a given radius"""
        
        s3={'in':'<', 'out':'>'}[direction]
        
        query="""
        MATCH (demand)<-[:HAS]-(a)-[chain:IS_CONNECTED*1..{radius}]-(terminus)-[:HAS]-(supply) 
        where a.{pk_name}={{{pk_name}}}
        and supply.type = demand.type 
        and supply.level = demand.level
        and SIGN(demand.value) {s3} SIGN(supply.value) 
        and all(r in chain where r.blocked = FALSE)
        return terminus, 
               COLLECT(DISTINCT supply) as inventory, 
               min(reduce(tot=0, r in chain | tot + r.max_cost)) AS minCost
        """.format(s3=s3, radius=radius, pk_name=self.pk_name)
        print query, {self.pk_name:self.pk}
        min_path_cost = graph.cypher.execute(query, {self.pk_name:self.pk})
        
        query="""
        MATCH (demand)<-[:HAS]-(a)-[chain:IS_CONNECTED*1..{radius}]-(terminus)-[:HAS]-(supply) 
        where a.{pk_name}={{{pk_name}}}
        and supply.type = demand.type 
        and supply.level = demand.level
        and SIGN(demand.value) {s3} SIGN(supply.value)  
        and all(r in chain where r.blocked = FALSE)
        RETURN terminus, chain, reduce(tot=0, r in chain | tot + r.max_cost) as totCost
        ORDER BY totCost
        """.format(s3=s3, radius=radius, pk_name=self.pk_name)
        paths = graph.cypher.execute(query, {self.pk_name:self.pk})
        
        source_costs = dict((rec.terminus[self.pk_name], {'minCost':rec.minCost, 'inventory':rec.inventory}) for rec in min_path_cost)

        return self._filter_paths(paths, source_costs, direction)
        
    def _filter_paths(self, paths, source_costs, direction):
        """ filter paths down to paths with the least weight between two nodes in the event
        that several paths with the same source and target are returned.
        """
        best_paths = defaultdict(list)
        for rec in paths:
            if rec.totCost == source_costs[rec.terminus[self.pk_name]]['minCost']:
                best_paths[rec.terminus].append(rec)

        
        # Expand the 'chain'
        supply_chains = []
        for terminus, recs in best_paths.iteritems():        
            paths = []
            paths_seen = {}
            for rec in recs:
                path = []
                path_names =  []
                for rel in rec.chain:
                    #path.extend(rel.nodes)
                    #if direction == 'in':
                    #    q,p = rel.nodes
                    #else:
                    #    p,q = rel.nodes
                    p,q = rel.nodes
                    if not path:
                        path =[p,q]
                        path_names = [p.ref, q.ref]
                    else:
                        if p.ref not in path_names:
                            g = p
                        else:
                            g = q
                        path.append(g)
                        path_names.append(g.ref)
                path_names = tuple(path_names)
                if not paths_seen.has_key(path_names):
                    paths.append(path)
                    paths_seen[path_names] = 1
            #paths = set(tuple(x) for x in paths) # Doesn't work. Should do this on the database
            #paths = dedupe(paths)
            supply_chains.append({'path':paths, 'inventory':source_costs[terminus[self.pk_name]]['inventory'], 
                                  'terminus':terminus, 'cost':rec.totCost})
        
        return supply_chains, best_paths
        
#I'm pretty sure there's a better way I could implement this on the python side.
# Feels fine on the database side, but the class api smells funny.
class Inventory(SimpleNode):
    types =  ['xmp', # XMP
              'res', # Resonator
              'fa',  # Force Amp
              'tur', # Turret
              'us',  # Ultra Strike
              'sh',  # Shield
              'hs',  # Heat Sink
              'mh',  # Multihack
              'us']  # Ultrastrike
    
    def __init__(self, pk, pk_name, attached_node_type='User'):
        self.pk = pk
        self.pk_name = pk_name
        self.attached_node_type = attached_node_type
        print "Get inv:", (self.nodetype, self.pk_name, self.pk)
        self.usernode = graph.find_one(attached_node_type, pk_name, pk)
    
    def find(self):
        query = """
        MATCH (user:User)-[r:HAS]->(b:Inventory)
        WHERE user.{pk_name} = {{{pk_name}}}
        RETURN b
        ORDER BY b.type, b.level
        """.format(pk_name=self.pk_name)
        print query
        d = OrderedDict()
        results = graph.cypher.execute(query, {self.pk_name:self.pk})
        for record in results:
            node = record[0]
            d[(node['type'], node['level'])] = node
        return d
    
    @property
    def nodes(self):
        return self.node
        
    def set(self, type, value, level=None):
        if value==0:
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
            print self.usernode
            print node
            graph.create(Relationship(self.usernode,'HAS',node))
    
    def delete(self, type, level=None):
        k = (type,level)
        if self.nodes.has_key(k):
            node = self.nodes.pop(k)
        query = """
        MATCH (n:Inventory)<-[:HAS]-(u:User)
        WHERE u.{pk_name} = {{{pk_name}}}
        AND   n.type = {{type}}
        AND   n.level = {{level}}
        DETACH DELETE n
        """.format(pk_name=self.pk_name)
        graph.cypher.execute(query, {self.pk_name:self.pk}, type=type, level=level)
        
        
class ConnectionSuggesterGM(object):
    def __init__(self, groupme_id, groupme_token):
        self.id=groupme_id
        self.user = User(groupme_id)
        self.gm   = GroupmeUser(groupme_token)
        self.neighbors = [n['groupme_id'] for n,_ in self.user.neighbors()]
        
    def new_connections(self,n=0):
        """
        Return users connected through groupme that are not connected to the
        current user in any way. 
        """
        if not hasattr(self, '_new_connections'):
            self._new_connections = []
            for sugg in self.gm.similar_users(n): # 0=no limit
            # Should I change this to use .verified_neighbors instead of .neighbors?
                if sugg['id'] not in self.neighbors:
                    self._new_connections.append(sugg)
            self._current_sort = 'groupmeGroups'
        return self._new_connections
        
    @property
    def verify_connections(self):
        """
        Find users who have connected to the current user, but the connection 
        as not been reciprocated.
        """
        if not hasattr(self, '_verify_connections'):
            self._verify_connections = self.user.unverified_neighbors_similarity()
            
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