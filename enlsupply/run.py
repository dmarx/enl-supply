# Basing this app off of
#   https://github.com/nicolewhite/neo4j-flask
#   http://nicolewhite.github.io/neo4j-flask/

from webapp import app
import os
from ConfigParser import ConfigParser
#from flask_oauth import OAuth

config = ConfigParser()
config.read('settings.cfg')
secret_key = config.get('app','secret_key')

#app.config['SERVER_NAME'] = 'enl.supply'
app.secret_key = secret_key
port = int(os.environ.get('PORT', 5000))
#app.debug = True
#app.run(host='0.0.0.0', port=port)
