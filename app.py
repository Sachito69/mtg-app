from app_core import app
from routes.tracker import tracker_bp
from routes.collection import collection_bp
from routes.main import main_bp
from routes.settings import settings_bp
from routes.community import community_bp
from routes.auth import auth_bp

app.register_blueprint(tracker_bp)
app.register_blueprint(collection_bp)
app.register_blueprint(main_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(community_bp)
app.register_blueprint(auth_bp)

if __name__ == "__main__":
    app.run(debug=True)
