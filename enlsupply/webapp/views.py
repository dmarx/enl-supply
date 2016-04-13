from models import User, Inventory, ConnectionSuggesterGM
from flask import Flask, request, session, redirect, render_template, \
                  flash, jsonify
from flask import url_for as base_url_for # to override
from utilities import verify_agent
from groupme_api import GroupmeUser
import os
from ConfigParser import ConfigParser
from collections import OrderedDict
#from flask_oauth import OAuth

config = ConfigParser()
config.read('settings.cfg')
app_token = config.get('io','app_token')
#app_token = os.environ.get('IO_APP_TOKEN') # how do we modify env settings in conda?

app = Flask(__name__)

# Is there any reason why Nicole doesn't attach the User object to the session?
# Seems like it would reduce requests to the database if we keep a pointer to
# the bound user node instead of querying the database every time we want it.


if os.name == 'posix': # Assume this means we're running on the server.
    print "Overriding url_for to force HTTPS"
    def url_for(url_rule, **kwargs):
        kwargs.setdefault('_external', True)
        kwargs.setdefault('_scheme', 'https')
        return base_url_for(url_rule, **kwargs)

    app.jinja_env.globals['url_for'] = url_for
else:
    url_for = base_url_for

@app.route('/test')
def test():
    print url_for('_hello_world', _external=True)
    return redirect(url_for('_hello_world', _external=True))

@app.route('/_hello_world')
def _hello_world():
    return 'Hello World!'

@app.route('/')
def index():
    inventory = None
    if session.has_key('username'):
        groupme_id = session['groupme_id']
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in Inventory(pk=groupme_id, pk_name="groupme_id").nodes.iteritems()]
    return render_template('index.html', inventory=inventory)
    
item_map = {"xmp":'XMP Bursters',
            "sh":'Shields',
            "res":'Resonators',
            "fat":'Force Amps/Turrets',
            "la":'Link Amps',
            "pc":'Power Cubes',
            "hs":'Heat Sinks',
            "mh":'Multi-Hacks',
            "jarvis":'Jarvis Virus',
            "ada":'ADA Virus'}
item_map = OrderedDict(sorted(item_map.iteritems(), key=lambda x: x[0]))

@app.route('/update_inventory')
def update_inventory():
    inventory = None
    if session.has_key('username'):
        groupme_id = session['groupme_id']
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in Inventory(pk=groupme_id, pk_name="groupme_id").nodes.iteritems()]
    return render_template('update_inventory.html', inventory=inventory, item_map=item_map)
    
# NB: At present, suggestions aren't even filtered on whether or not a user is already 
# connected to that person. We should only suggest connections that a user isn't already connected to.
@app.route('/connections')
def connections():
    verified_neighbors = None
    if session.has_key('username'):
        user = User(session['groupme_id'])
        #gm = GroupmeUser(session['groupme_token'])
        #verified_neighbors = [neighbor for neighbor,_ in user.verified_neighbors()]
        #suggestions = gm.similar_users(50)
        sugg = ConnectionSuggesterGM(session['groupme_id'], session['groupme_token'])
        verified_neighbors = [neighbor for neighbor,_ in sugg.user.verified_neighbors()]
        #verified_neighbors.sort()
        verified_neighbors = sorted(verified_neighbors, key=lambda x: x['agent_name'].lower())
        suggestions = sugg.new_connections()
        return render_template('connections.html', 
                               verified_neighbors=verified_neighbors,
                               suggestions=suggestions) 
    else:
        return redirect(url_for('index'))

@app.route('/supply_me')
def supply_me():
    paths = None
    if session.has_key('username'):
        user = User(session['groupme_id'])
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in user.inventory.nodes.iteritems()]
        paths,_ = user.supply_paths(direction='in')
        paths = sorted(paths, key=lambda k: (k['cost'], k['terminus']))
    return render_template('supply_me.html', paths=paths, inventory=inventory, item_map=item_map)
    

@app.route('/unload_me')
def unload_me():
    paths = None
    if session.has_key('username'):
        user = User(session['groupme_id'])
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in user.inventory.nodes.iteritems()]
        paths,_ = user.supply_paths(direction='out')
        paths = sorted(paths, key=lambda k: (k['cost'], k['path'][1]['username']))
    return render_template('unload_me.html', paths=paths, inventory=inventory, item_map=item_map)
    
# the connections, supply_me, supply_team endpoints are all very similar. Could
# probably DRY out my code with a custom decorator or factory function or something.


@app.route('/login', methods=['GET', 'POST'])
def login():
    return render_template('login.html')

@app.route('/about', methods=['GET'])
def about():
    return render_template('about.html')
    
@app.route('/_groupme_callback', methods=['GET'])   
def _groupme_callback():
    access_token = request.args.get('access_token')
    gm = GroupmeUser(access_token)
    username = verify_agent(id=gm.id, token=app_token, service='groupme')
    if not username:
        flash('Invalid login.')
        if access_token:
            flash('Access token from groupme received, but unable to confirm your identitiy as an Enlightened Agent. Visit http://enl.io for additional authentication.')
        return render_template('login.html')
    else:
        session['username'] = username
        session['groupme_id'] = gm.id
        session['groupme_token'] = access_token
        User(groupme_id = gm.id, groupme_nick=gm.nickname, agent_name=username)
        print "callback", session['groupme_id']
        flash('Logged in.')
        return redirect(url_for('index'))
    
@app.route('/_submit_new_connections')
def _submit_new_connections():
    """
    Receives groupme_ids from connections.html AJAX call. Runs agent 
    verification (and in the future, !met verification) on each ID. Sends IDs 
    and agentnames to models.User.add_verified_relationship to create 
    appropriate edges. Returns list of IDs for whom agent verification (and/or
    !met verification) was unsuccessful.
    """
    print "Message recieved"
    user_ids = request.args.get('groupme_ids').split(',')
    access_token = request.args.get('access_token')
    gm = GroupmeUser(access_token)
    user = User(session['groupme_id'])
    verified = []
    io_verif_fail = []
    print user_ids
    print type(user_ids)
    print(len(user_ids))
    for id in user_ids:
        agent = verify_agent(id=id, token=app_token, service='groupme')
        if agent:
            print "Adding link {src} -> {tgt}".format(src=user.agent_name, tgt=agent)
            user.add_verified_relationship(groupme_id=id, agent_name=agent, cost=1)
        else:
            io_verif_fail.append(id)
    #return redirect(url_for('connections')) 
    #print "Returning response"
    return jsonify(result=None)
    # This endpoint is looking for AJAX/json data, so the redirect doesn't do anything.
    
@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('groupme_id', None)
    flash('Logged out.')
    return redirect(url_for('index'))
    
@app.route('/add_inventory', methods=['POST'])
def add_inventory():
    type = request.form['type']
    level = request.form['level']
    value = int(request.form['value'])

    if not type or not level:
        flash('You must specify item type and level.')
    else:
        User(session['groupme_id']).inventory.set(type=type, level=level, value=value)

    return redirect(url_for('update_inventory'))
