from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()


class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    username     = db.Column(db.String(100), unique=True, nullable=True)
    email        = db.Column(db.String(100), unique=True, nullable=False)
    password     = db.Column(db.String(100), nullable=False)
    phone        = db.Column(db.String(20), nullable=True)  # String not Integer
    image        = db.Column(db.String(255))
    id_image     = db.Column(db.String(255))
    is_approved  = db.Column(db.Boolean, default=False)
    gold_coins   = db.Column(db.BigInteger, default=0)  # NEW
    usdt_wallet  = db.Column(db.String(200), nullable=True)
    btc_wallet   = db.Column(db.String(200), nullable=True)
    jazz_number  = db.Column(db.String(20), nullable=True)   # NEW
    easy_number  = db.Column(db.String(20), nullable=True)   # NEW
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':          self.id,
            'name':        self.name,
            'username':    self.username,
            'email':       self.email,
            'phone':       self.phone,
            'image':       self.image,
            'is_approved': self.is_approved,
            'gold_coins':  self.gold_coins,
            'usdt_wallet': self.usdt_wallet,
            'btc_wallet':  self.btc_wallet,
        }


class Stake(db.Model):
    __tablename__ = 'stakes'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    currency     = db.Column(db.String(10), nullable=False)  # always "gold"
    amount       = db.Column(db.Float, nullable=False)       # USDT equivalent
    gold_amount  = db.Column(db.BigInteger, nullable=False, default=0)  # NEW — actual gold coins staked
    profit_rate  = db.Column(db.Float, default=0.10)
    penalty_rate = db.Column(db.Float, default=0.05)
    start_time   = db.Column(db.DateTime, default=datetime.utcnow)
    end_time     = db.Column(db.DateTime)
    status       = db.Column(db.String(20), default='active')
    tx_hash      = db.Column(db.String(200), nullable=True)

    def __init__(self, user_id, currency, amount, gold_amount):
        self.user_id      = user_id
        self.currency     = currency
        self.amount       = amount
        self.gold_amount  = gold_amount
        self.profit_rate  = 0.10
        self.penalty_rate = 0.05
        self.start_time   = datetime.utcnow()
        self.end_time     = datetime.utcnow() + timedelta(days=7)
        self.status       = 'active'

    def is_matured(self):
        return datetime.utcnow() >= self.end_time

    def days_remaining(self):
        if self.is_matured(): return 0
        return (self.end_time - datetime.utcnow()).days

    def seconds_remaining(self):
        if self.is_matured(): return 0
        return int((self.end_time - datetime.utcnow()).total_seconds())

    def profit_amount(self):
        return round(self.amount * self.profit_rate, 6)

    def penalty_amount(self):
        return round(self.amount * self.penalty_rate, 6)

    def payout_amount(self):
        return round(self.amount + self.profit_amount(), 6)

    def early_payout_amount(self):
        return round(self.amount - self.penalty_amount(), 6)

    # NEW — gold coin equivalents
    def gold_payout(self):
        return int(self.gold_amount * (1 + self.profit_rate))

    def gold_partial_early_payout(self, partial_gold):
        return int(partial_gold * (1 - self.penalty_rate))

    def gold_early_payout(self):
        return int(self.gold_amount * (1 - self.penalty_rate))

    def to_dict(self):
        return {
            'id':                self.id,
            'user_id':           self.user_id,
            'currency':          self.currency,
            'amount':            self.amount,
            'gold_amount':       self.gold_amount,
            'profit_rate':       self.profit_rate,
            'penalty_rate':      self.penalty_rate,
            'start_time':        str(self.start_time),
            'end_time':          str(self.end_time),
            'status':            self.status,
            'is_matured':        self.is_matured(),
            'days_remaining':    self.days_remaining(),
            'seconds_remaining': self.seconds_remaining(),
            'profit_amount':     self.profit_amount(),
            'payout_amount':     self.payout_amount(),
            'early_payout':      self.early_payout_amount(),
            'gold_payout':       self.gold_payout(),       # NEW
            'gold_early_payout': self.gold_early_payout(), # NEW
        }


class PendingPayment(db.Model):
    __tablename__ = 'pending_payments'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount_usd     = db.Column(db.Float, nullable=False)
    gold_coins     = db.Column(db.BigInteger, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)  # "pkr" or "usdt"
    screenshot     = db.Column(db.String(255), nullable=False)
    status         = db.Column(db.String(20), default='pending')
    # pending / approved / rejected
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at    = db.Column(db.DateTime, nullable=True)
    credited       = db.Column(db.Boolean, default=False)  # has game collected this?

    def to_dict(self):
        return {
            'id':             self.id,
            'user_id':        self.user_id,
            'amount_usd':     self.amount_usd,
            'gold_coins':     self.gold_coins,
            'payment_method': self.payment_method,
            'screenshot':     self.screenshot,
            'status':         self.status,
            'created_at':     str(self.created_at),
            'reviewed_at':    str(self.reviewed_at) if self.reviewed_at else None,
            'credited':       self.credited,
        }


class WithdrawRequest(db.Model):
    __tablename__ = 'withdraw_requests'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    gold_amount    = db.Column(db.BigInteger, nullable=False)
    usdt_amount    = db.Column(db.Float, nullable=False)
    pkr_amount     = db.Column(db.Float, nullable=True)
    method         = db.Column(db.String(20), nullable=False)
    # "tron" / "bsc" / "eth" / "jazzcash" / "easypaisa"
    destination    = db.Column(db.String(200), nullable=False)
    # wallet address for USDT, phone number for PKR
    status         = db.Column(db.String(20), default='pending')
    # pending / processing / completed / rejected
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at   = db.Column(db.DateTime, nullable=True)
    admin_note     = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            'id':           self.id,
            'user_id':      self.user_id,
            'gold_amount':  self.gold_amount,
            'usdt_amount':  self.usdt_amount,
            'pkr_amount':   self.pkr_amount,
            'method':       self.method,
            'destination':  self.destination,
            'status':       self.status,
            'created_at':   str(self.created_at),
            'completed_at': str(self.completed_at) if self.completed_at else None,
            'admin_note':   self.admin_note,
        }