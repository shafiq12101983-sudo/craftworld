from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()

class User(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    email          = db.Column(db.String(100), unique=True, nullable=False)
    password       = db.Column(db.String(100), unique=True, nullable=False)
    phone          = db.Column(db.Integer, nullable=True)
    image          = db.Column(db.String(255))
    is_approved    = db.Column(db.Boolean, default=False)
    usdt_wallet = db.Column(db.String(200),
                            nullable=True)
    btc_wallet = db.Column(db.String(200),
                           nullable=True)


    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'image': self.image,
            'is_approved': self.is_approved,
            'vether_balance': self.vether_balance,
            'usdt_wallet': self.usdt_wallet,
            'btc_wallet': self.btc_wallet
        }

class Stake(db.Model):
    __tablename__ = 'stakes'

    id = db.Column(db.Integer,
                   primary_key=True)
    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id'),
                        nullable=False)
    currency = db.Column(db.String(10),
                         nullable=False)  # USDT or BTC
    amount = db.Column(db.Float,
                       nullable=False)
    profit_rate = db.Column(db.Float,
                            default=0.10)
    penalty_rate = db.Column(db.Float,
                             default=0.05)
    start_time = db.Column(db.DateTime,
                           default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(20),
                       default='active')
    # active / completed / cancelled
    tx_hash = db.Column(db.String(200),
                        nullable=True)

    def __init__(self, user_id, currency,
                 amount):
        self.user_id = user_id
        self.currency = currency
        self.amount = amount
        self.profit_rate = 0.10
        self.penalty_rate = 0.05
        self.start_time = datetime.utcnow()
        self.end_time = (datetime.utcnow()
                         + timedelta(days=7))
        self.status = 'active'

    def is_matured(self):
        return datetime.utcnow() >= self.end_time

    def days_remaining(self):
        if self.is_matured():
            return 0
        delta = self.end_time \
                - datetime.utcnow()
        return delta.days

    def seconds_remaining(self):
        if self.is_matured():
            return 0
        delta = self.end_time \
                - datetime.utcnow()
        return int(delta.total_seconds())

    def profit_amount(self):
        return round(
            self.amount * self.profit_rate,
            6)

    def penalty_amount(self):
        return round(
            self.amount * self.penalty_rate,
            6)

    def payout_amount(self):
        # full payout with profit
        return round(
            self.amount + self.profit_amount(),
            6)

    def early_payout_amount(self):
        # early unstake — lose 5%
        return round(
            self.amount - self.penalty_amount(),
            6)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'currency': self.currency,
            'amount': self.amount,
            'profit_rate': self.profit_rate,
            'penalty_rate': self.penalty_rate,
            'start_time': str(self.start_time),
            'end_time': str(self.end_time),
            'status': self.status,
            'is_matured': self.is_matured(),
            'days_remaining': self.days_remaining(),
            'seconds_remaining':
                self.seconds_remaining(),
            'profit_amount': self.profit_amount(),
            'payout_amount': self.payout_amount(),
            'early_payout':
                self.early_payout_amount()
        }