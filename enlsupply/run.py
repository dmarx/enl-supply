# Basing this app off of
#   https://github.com/nicolewhite/neo4j-flask
#   http://nicolewhite.github.io/neo4j-flask/

from webapp import app
import os

app.debug = True
app.secret_key = os.urandom(24)
port = int(os.environ.get('PORT', 5000))
app.run(host='0.0.0.0', port=port)