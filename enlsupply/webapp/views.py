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
        username = session['username']
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} for k,v in Inventory(username).nodes.iteritems()]
    return render_template('index.html', inventory=inventory)

@app.route('/connections')
def connections():
    verified_neighbors = None
    if session.has_key('username'):
        user = User(session['username'])
        verified_neighbors = [neighbor for neighbor,_ in user.verified_neighbors()]
    return render_template('connections.html', verified_neighbors=verified_neighbors)

@app.route('/supply_me')
def supply_me():
    paths = None
    if session.has_key('username'):
        user = User(session['username'])
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in user.inventory.nodes.iteritems()]
        paths,_ = user.supply_paths(direction='in')
        paths = sorted(paths, key=lambda k: (k['cost'], k['path'][1]['username']))
    return render_template('supply_me.html', paths=paths, inventory=inventory)
    

@app.route('/supply_team')
def supply_team():
    paths = None
    if session.has_key('username'):
        user = User(session['username'])
        inventory = [{'type':k[0], 'level':k[1], 'value':v['value']} 
                     for k,v in user.inventory.nodes.iteritems()]
        paths,_ = user.supply_paths(direction='out')
        paths = sorted(paths, key=lambda k: (k['cost'], k['path'][1]['username']))
    return render_template('supply_team.html', paths=paths, inventory=inventory)
    
# the connections, supply_me, supply_team endpoints are all very similar. Could
# probably DRY out my code with a custom decorator or factory function or something.
    
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if len(username) < 1:
            flash('Your username must be at least one character.')
        elif len(password) < 5:
            flash('Your password must be at least 5 characters.')
        elif not User(username).register(password):
            flash('A user with that username already exists.')
        else:
            session['username'] = username
            flash('Logged in.')
            return redirect(url_for('index'))

    return render_template('register.html')

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
            flash('Access token from groupme received. Visit http://enl.io for additional authentication.')
        return render_template('login.html')
    else:
        session['username'] = username
        flash('Logged in.')
        return redirect(url_for('index'))
    
@app.route('/logout')
def logout():
    session.pop('username', None)
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
        User(session['username']).inventory.set(type=type, level=level, value=value)

    return redirect(url_for('index'))