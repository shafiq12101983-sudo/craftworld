# test_db.py
from app import app
from models import User, Stake
import json

with (app.app_context()):
    users = User.query.all()
    stakes = User.query.all()
    print(f"Total users: {len(users)}")
    print(f"Total stakes: {len(stakes)}")
    for user in users:
        print(json.dumps(user.to_dict(), indent=2, default=str))
    for stake in stakes:
        print()
        print(json.dumps(stake.to_dict(), indent=2, default=str))