import networkx as nx
from collections import Counter, defaultdict
import random # for the demo
import os
from py2neo import Graph, Node, Relationship, authenticate
#from ..models import User

url = os.environ.get('GRAPHENEDB_URL', 'http://localhost:7474') # GrapheneDB is Heroku's Neo4j as a service
username = os.environ.get('NEO4J_USERNAME', 'neo4j')
password = os.environ.get('NEO4J_PASSWORD', 'dev_p4ss') # Need to change password to use authentication neoauth neo4j neo4j dev_p4ss

if username and password:
    authenticate(url.strip('http://'), username, password)

graph = Graph(url + '/db/data/')

def generate_transport_problem(
    n_nodes = 50,
    n_item_types = 5,
    max_degree = 5, # This should be fun
    ba_edges = 2, #barabasi-albert tuning parameter
    perc_sparsity = .9,
    supply_demand_balance = .5,
    inv_scalar = 100
    ):
    """
    Generate a transport problem
    """
    attr_d = defaultdict(Counter)

    for i in range(n_item_types):
        for j in range(n_nodes):
            if random.random() < perc_sparsity: # Does this node have non-zero inventory for this item?
                continue
            s = 1
            if random.random() < supply_demand_balance: # What is the sign on the item's inventory?
                s = -1
            attr_d['item'+str(i)][str(j)] = s*int(inv_scalar * random.random())

    g = nx.barabasi_albert_graph(n_nodes, ba_edges)
    g = nx.relabel_nodes(g, {n:str(n) for n in range(n_nodes)})

    for _,d in g.nodes(data=True):
        d['max_degree'] = max_degree

    # Set all edges to default weight of '1'
    for u,v,d in g.edges(data=True):
        d['cost'] = 1 # I should play with this

    for k,v in attr_d.items():
        d = dict(v)
        d.update({a:0 for a in g.nodes() if a not in d.keys()}) # Explicitly add node attributes for zero inventory nodes
        nx.set_node_attributes(g, k, d)

    return g, attr_d
 
#graph.delete_all()
 
# Generate a graph 
g, attr_d = generate_transport_problem()

# Push the graph to neo
for n in g.nodes():
    node = Node("User", username=n)
    graph.create(node)
    
for p,q in g.edges():
    src = graph.find_one("User", "username", p)
    tgt = graph.find_one("User", "username", q)
    rel = Relationship(src, "CAN_REACH", tgt)
    graph.create(rel)
    
for a,d in attr_d.iteritems():
    for u,v in d.iteritems():
        inv = Node("Item", type=a, value=v)
        user = graph.find_one("User", "username", u)
        rel = Relationship(user, "HAS", inv)
        graph.create(rel)
        
