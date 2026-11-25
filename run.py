"""Entry point:  python run.py"""
from backend.app import create_app
from backend.config import Config
from backend.reminder_scheduler import start_scheduler

app = create_app()

if __name__ == "__main__":
    start_scheduler()
    print(f"\n  CampusAI is running -> http://{Config.HOST}:{Config.PORT}\n")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, use_reloader=False)
