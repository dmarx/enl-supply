from models import User, Inventory
from flask import Flask, request, session, redirect, url_for, render_template, flash
from utilities import verify_agent
from groupme_api import GroupmeUser
import os
from ConfigParser import ConfigParser
#from flask_oauth import OAuth

config = ConfigParser()
config.read('settings.cfg')
app_token = config.get('io','app_token')
#app_token = os.environ.get('IO_APP_TOKEN') # how do we modify env settings in conda?

app = Flask(__name__)

# Is there any reason why Nicole doesn't attach the User object to the session?
# Seems like it would reduce requests to the database if we keep a pointer to
# the bound user node instead of querying the database every time we want it.

@app.route('/')
def index():
    inventory = None
    if session.has_key('username'):
        groupme_id = session['groupme_id']
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in Inventory(pk=groupme_id, pk_name="groupme_id").nodes.iteritems()]
    return render_template('index.html', inventory=inventory)

@app.route('/update_inventory')
def update_inventory():
    inventory = None
    if session.has_key('username'):
        groupme_id = session['groupme_id']
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in Inventory(pk=groupme_id, pk_name="groupme_id").nodes.iteritems()]
    return render_template('update_inventory.html', inventory=inventory)
    
@app.route('/connections')
def connections():
    verified_neighbors = None
    if session.has_key('username'):
        user = User(session['groupme_id'])
        gm = GroupmeUser(session['groupme_token'])
        verified_neighbors = [neighbor for neighbor,_ in user.verified_neighbors()]
        return render_template('connections.html', 
                               verified_neighbors=verified_neighbors,
                               suggestions=gm.similar_users(50))
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
        paths = sorted(paths, key=lambda k: (k['cost'], k['path'][1]['username']))
    return render_template('supply_me.html', paths=paths, inventory=inventory)
    

@app.route('/supply_team')
def supply_team():
    paths = None
    if session.has_key('username'):
        user = User(session['groupme_id'])
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in user.inventory.nodes.iteritems()]
        paths,_ = user.supply_paths(direction='out')
        paths = sorted(paths, key=lambda k: (k['cost'], k['path'][1]['username']))
    return render_template('supply_team.html', paths=paths, inventory=inventory)
    
# the connections, supply_me, supply_team endpoints are all very similar. Could
# probably DRY out my code with a custom decorator or factory function or something.


@app.route('/login', methods=['GET', 'POST'])
def login():
    return render_template('login.html')
   
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