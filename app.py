import os
import json
import time
import base64
import hashlib
import requests
from datetime import datetime
from flask import (Flask, request, jsonify,
                   render_template,
                   redirect, url_for,
                   send_from_directory)
from werkzeug.utils import secure_filename
from models import db, User, Stake, PendingPayment, WithdrawRequest
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
UPLOAD_FOLDER      = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}git
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── CRYPTOMUS KEYS ──
MERCHANT_UUID = '40ae3325-2bc6-42df-b47a-eba41b8bad33'
PAYMENT_KEY   = '35d7eea1b7e088ee2784ff199af823cdf190fd0b'
PAYOUT_KEY    = 'sgO0zQzV6jBCH3gJat0JChhAjUZlSm0kZCCBvqRX0JziWUmLC0UqBoI6iO8lsKvw5nDSQesAS8g1m2arnL4VxtB94T1bBelScvmIzIet8MAS6ErRMDel2Q3UUUDpz5Wh'

# ── RATES ──
RATE     = 10_000.0  # gold coins per $1 USDT
PKR_RATE = 280.0     # PKR per $1 USDT

# ── VETHER (kept for legacy) ──
VETHER_PER_USD      = 500
VETHER_WITHDRAW_RATE = 600
MIN_WITHDRAW_VETHER  = 3_000

# ── MINERAL COIN RATES PER LEVEL ──
COINS_PER_USD = [
    15_000,  # LV1  Iron
    11_000,  # LV2  Copper
     8_000,  # LV3  Silver
     6_000,  # LV4  Gold
     4_500,  # LV5  Platinum
     3_200,  # LV6  Titanium
     2_200,  # LV7  Crystal
     1_500,  # LV8  Iridium
       900,  # LV9  Osmium
       500   # LV10 Vether
]

BUY_COINS_PER_USD = [
    int(r * 0.80) for r in COINS_PER_USD
]

with app.app_context():
    db.create_all()

# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════
def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() \
           in ALLOWED_EXTENSIONS

def make_sign(data, api_key):
    if data:
        json_data   = json.dumps(data)
        base64_data = base64.b64encode(
            json_data.encode()).decode()
    else:
        base64_data = ''
    return hashlib.md5(
        (base64_data + api_key
         ).encode()).hexdigest()

def call_cryptomus(endpoint, data, api_key):
    sign = make_sign(data, api_key)
    headers = {
        'merchant':     MERCHANT_UUID,
        'sign':         sign,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(
            f'https://api.cryptomus.com/v1/{endpoint}',
            json=data,
            headers=headers,
            timeout=30
        )
        return response.json()
    except Exception as e:
        return {'error': str(e)}

# ═══════════════════════════════════════════
# USER ROUTES
# ═══════════════════════════════════════════
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/api/users', methods=['POST'])
def add_user():
    data = request.get_json() \
        if request.is_json \
        else request.form

    name     = data.get("name")
    email    = data.get("email")
    password = data.get("password")
    phone    = data.get("phone")
    username = data.get("username")

    if not name or not email:
        return jsonify(
            {"error": "Name and Email required"}
        ), 400

    if User.query.filter_by(
            email=email).first():
        return jsonify(
            {"error": "Email already exists"}
        ), 409

    if username and User.query.filter_by(
            username=username).first():
        return jsonify(
            {"error": "Username already exists"}
        ), 409

    user = User(
        name       = name,
        email      = email,
        password   = password,
        phone      = str(phone) if phone else None,
        username   = username,
        is_approved = False,
        gold_coins  = 0
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({
        "message": "Account created.",
        "user_id": user.id
    }), 201


@app.route('/api/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify(
        [u.to_dict() for u in users]), 200


@app.route('/api/verify', methods=['POST'])
def verify_user():
    player_id = request.form.get("player_id")
    if not player_id:
        return jsonify(
            {"error": "Player ID required"}), 400

    user = User.query.get(player_id)
    if not user:
        return jsonify(
            {"error": "User not found"}), 404

    selfie_file = request.files.get("selfie")
    id_file     = request.files.get("id_doc")

    if not selfie_file or not id_file:
        return jsonify({
            "error": "Both selfie and ID "
                     "document are required"
        }), 400

    if allowed_file(selfie_file.filename) \
            and allowed_file(id_file.filename):
        s_filename = secure_filename(
            f"selfie_{player_id}"
            f"_{selfie_file.filename}")
        selfie_file.save(os.path.join(
            app.config["UPLOAD_FOLDER"],
            s_filename))

        id_filename = secure_filename(
            f"id_{player_id}"
            f"_{id_file.filename}")
        id_file.save(os.path.join(
            app.config["UPLOAD_FOLDER"],
            id_filename))

        user.image    = s_filename
        user.id_image = id_filename
        db.session.commit()

        return jsonify({
            "message": "Verification documents "
                       "uploaded successfully"
        }), 200

    return jsonify(
        {"error": "Invalid file format"}), 400


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], filename)


# ═══════════════════════════════════════════
# PLAYER SYNC
# Game calls this on resume/login
# returns gold balance + pending credits
# ═══════════════════════════════════════════
@app.route('/api/player/sync/<player_id>',
           methods=['GET'])
def sync_player(player_id):
    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    # collect approved payments
    # not yet credited to game
    approved = PendingPayment.query.filter_by(
        user_id  = player_id_int,
        status   = 'approved',
        credited = False
    ).all()

    pending_gold = sum(
        p.gold_coins for p in approved)

    for p in approved:
        p.credited = True

    if pending_gold > 0:
        user.gold_coins = (
            user.gold_coins or 0) \
            + pending_gold

    db.session.commit()

    return jsonify({
        "player_id":    player_id_int,
        "gold_coins":   user.gold_coins,
        "pending_gold": pending_gold,
        "is_approved":  user.is_approved,
        "username":     user.username,
    }), 200


# ═══════════════════════════════════════════
# BUY — SCREENSHOT PAYMENT
# ═══════════════════════════════════════════
@app.route('/api/payment/submit_screenshot',
           methods=['POST'])
def submit_screenshot():
    body = request.json
    if not body:
        return jsonify(
            {"error": "No data"}), 400

    player_id      = body.get('player_id')
    amount_usd     = body.get('amount_usd')
    gold_coins     = body.get('gold_coins')
    payment_method = body.get('payment_method')
    screenshot_b64 = body.get('screenshot')

    if not all([player_id, amount_usd,
                gold_coins, screenshot_b64,
                payment_method]):
        return jsonify(
            {"error": "Missing fields"}), 400

    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    try:
        image_data = base64.b64decode(
            screenshot_b64)
        filename = secure_filename(
            f"payment_{player_id_int}"
            f"_{int(time.time())}.jpg")
        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename)
        with open(filepath, 'wb') as f:
            f.write(image_data)
    except Exception:
        return jsonify(
            {"error": "Invalid image data"}), 400

    payment = PendingPayment(
        user_id        = player_id_int,
        amount_usd     = float(amount_usd),
        gold_coins     = int(gold_coins),
        payment_method = payment_method,
        screenshot     = filename,
        status         = 'pending',
        credited       = False
    )
    db.session.add(payment)
    db.session.commit()

    print(f'\nScreenshot submitted:'
          f'\nPlayer: {player_id_int}'
          f'\nAmount: ${amount_usd}'
          f'\nGold: {gold_coins}'
          f'\nMethod: {payment_method}')

    return jsonify({
        "message":    "Payment submitted for review",
        "payment_id": payment.id,
        "status":     "pending"
    }), 200


# ═══════════════════════════════════════════
# POLL PENDING CREDITS
# Kept separate from sync for explicit polling
# ═══════════════════════════════════════════
@app.route('/api/payment/pending_credits'
           '/<player_id>',
           methods=['GET'])
def pending_credits(player_id):
    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    approved = PendingPayment.query.filter_by(
        user_id  = player_id_int,
        status   = 'approved',
        credited = False
    ).all()

    total_gold = sum(
        p.gold_coins for p in approved)

    for p in approved:
        p.credited = True
    db.session.commit()

    return jsonify({
        "gold_to_credit": total_gold,
        "payments_count": len(approved)
    }), 200


# ═══════════════════════════════════════════
# STAKE ROUTES
# ═══════════════════════════════════════════
@app.route('/api/stake/create',
           methods=['POST'])
def create_stake():
    body = request.json
    if not body:
        return jsonify(
            {"error": "No data"}), 400

    player_id   = body.get('player_id')
    currency    = body.get('currency', 'gold')
    amount      = body.get('amount', 0)
    gold_amount = body.get('gold_amount', 0)

    if not player_id:
        return jsonify(
            {"error": "Player ID required"}), 400

    if float(amount) < 10:
        return jsonify({
            "error": "Minimum stake is $10"
        }), 400

    if int(gold_amount) <= 0:
        return jsonify({
            "error": "Invalid gold amount"
        }), 400

    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    if (user.gold_coins or 0) < int(gold_amount):
        return jsonify({
            "error": "Insufficient gold coins"
        }), 400

    active_stakes = Stake.query.filter_by(
        user_id = player_id_int,
        status  = 'active').count()
    if active_stakes >= 3:
        return jsonify({
            "error": "Maximum 3 active "
                     "stakes allowed"
        }), 400

    user.gold_coins = (
        user.gold_coins or 0) \
        - int(gold_amount)

    stake = Stake(
        user_id     = player_id_int,
        currency    = currency,
        amount      = float(amount),
        gold_amount = int(gold_amount)
    )
    db.session.add(stake)
    db.session.commit()

    return jsonify({
        "message":     "Stake created",
        "stake":       stake.to_dict(),
        "end_time":    str(stake.end_time),
        "gold_payout": stake.gold_payout()
    }), 200


@app.route('/api/stake/list/<player_id>',
           methods=['GET'])
def get_stakes(player_id):
    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    stakes = Stake.query.filter_by(
        user_id=player_id_int).order_by(
        Stake.start_time.desc()).all()

    return jsonify({
        "stakes": [s.to_dict()
                   for s in stakes],
        "active_count": sum(
            1 for s in stakes
            if s.status == 'active'),
        "total_staked": sum(
            s.amount for s in stakes
            if s.status == 'active')
    }), 200


@app.route('/api/stake/claim',
           methods=['POST'])
def claim_stake():
    body = request.json
    if not body:
        return jsonify(
            {"error": "No data"}), 400

    player_id = body.get('player_id')
    stake_id  = body.get('stake_id')

    try:
        player_id_int = int(player_id)
        stake_id_int  = int(stake_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid IDs"}), 400

    stake = Stake.query.filter_by(
        id      = stake_id_int,
        user_id = player_id_int,
        status  = 'active').first()

    if not stake:
        return jsonify(
            {"error": "Stake not found"}), 404

    if not stake.is_matured():
        return jsonify({
            "error": "Stake not matured yet",
            "seconds_remaining":
                stake.seconds_remaining()
        }), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    gold_to_return = stake.gold_payout()

    user.gold_coins = (
        user.gold_coins or 0) \
        + gold_to_return

    stake.status = 'completed'
    db.session.commit()

    print(f'\nStake claimed:'
          f'\nPlayer: {player_id_int}'
          f'\nGold returned: {gold_to_return}')

    return jsonify({
        "message":        "Stake claimed",
        "gold_to_credit": gold_to_return,
        "payout_usdt":    stake.payout_amount(),
        "status":         "completed"
    }), 200


@app.route('/api/stake/unstake',
           methods=['POST'])
def unstake():
    body = request.json
    if not body:
        return jsonify(
            {"error": "No data"}), 400

    player_id = body.get('player_id')
    stake_id  = body.get('stake_id')

    try:
        player_id_int = int(player_id)
        stake_id_int  = int(stake_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid IDs"}), 400

    stake = Stake.query.filter_by(
        id      = stake_id_int,
        user_id = player_id_int,
        status  = 'active').first()

    if not stake:
        return jsonify(
            {"error": "Stake not found"}), 404

    if stake.is_matured():
        return jsonify({
            "error": "Stake matured — "
                     "use /claim instead"
        }), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    gold_to_return = stake.gold_early_payout()

    user.gold_coins = (
        user.gold_coins or 0) \
        + gold_to_return

    stake.status = 'cancelled'
    db.session.commit()

    print(f'\nEarly unstake:'
          f'\nPlayer: {player_id_int}'
          f'\nGold returned: {gold_to_return}')

    return jsonify({
        "message":         "Unstaked early",
        "gold_to_credit":  gold_to_return,
        "penalty_gold":    stake.gold_amount
                           - gold_to_return,
        "early_payout_usdt":
            stake.early_payout_amount(),
        "status":          "cancelled"
    }), 200


# ═══════════════════════════════════════════
# WITHDRAWAL ROUTES
# ═══════════════════════════════════════════
@app.route('/api/withdraw/submit',
           methods=['POST'])
def submit_withdrawal():
    body = request.json
    if not body:
        return jsonify(
            {"error": "No data"}), 400

    player_id   = body.get('player_id')
    gold_amount = body.get('gold_amount', 0)
    method      = body.get('method')
    destination = body.get('destination')

    if not all([player_id, method,
                destination]):
        return jsonify(
            {"error": "Missing fields"}), 400

    if int(gold_amount) <= 0:
        return jsonify(
            {"error": "Invalid amount"}), 400

    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
            {"error": "Invalid player ID"}), 400

    user = User.query.filter_by(
        id=player_id_int).first()
    if not user:
        return jsonify(
            {"error": "Player not found"}), 404

    if not user.is_approved:
        return jsonify({
            "error": "Account not verified. "
                     "Complete KYC first."
        }), 403

    if (user.gold_coins or 0) \
            < int(gold_amount):
        return jsonify({
            "error": "Insufficient gold coins"
        }), 400

    usdt_amount = round(
        int(gold_amount) / RATE, 4)

    if usdt_amount < 5.0:
        return jsonify({
            "error": "Minimum withdrawal "
                     "is $5.00 USDT"
        }), 400

    pkr_amount = None
    if method in ['jazzcash', 'easypaisa']:
        pkr_amount = round(
            usdt_amount * PKR_RATE, 2)
        if method == 'jazzcash':
            user.jazz_number = destination
        else:
            user.easy_number = destination

    # deduct immediately
    user.gold_coins = (
        user.gold_coins or 0) \
        - int(gold_amount)

    withdraw = WithdrawRequest(
        user_id     = player_id_int,
        gold_amount = int(gold_amount),
        usdt_amount = usdt_amount,
        pkr_amount  = pkr_amount,
        method      = method,
        destination = destination,
        status      = 'pending'
    )
    db.session.add(withdraw)
    db.session.commit()

    order_id = (f"withdraw_{player_id_int}"
                f"_{withdraw.id}"
                f"_{int(time.time())}")

    print(f'\nWithdrawal request:'
          f'\nPlayer: {player_id_int}'
          f'\nGold: {gold_amount}'
          f'\nUSDT: {usdt_amount}'
          f'\nPKR: {pkr_amount}'
          f'\nMethod: {method}'
          f'\nTo: {destination}')

    return jsonify({
        "message":     "Withdrawal submitted",
        "order_id":    order_id,
        "usd_amount":  usdt_amount,
        "pkr_amount":  pkr_amount,
        "gold_amount": gold_amount,
        "status":      "pending"
    }), 200


# ═══════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════
@app.route('/admin')
def admin_panel():
    users = User.query.all()
    pending_pays = PendingPayment.query\
        .filter_by(status='pending')\
        .order_by(PendingPayment.created_at
                  .desc()).all()
    pending_wds = WithdrawRequest.query\
        .filter_by(status='pending')\
        .order_by(WithdrawRequest.created_at
                  .desc()).all()
    return render_template(
        'adminpanel.html',
        users        = users,
        pending_pays = pending_pays,
        pending_wds  = pending_wds)


@app.route('/approve/<int:user_id>')
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    return redirect(url_for('admin_panel'))


@app.route('/delete/<int:user_id>')
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('admin_panel'))


@app.route('/admin/approve_payment'
           '/<int:payment_id>',
           methods=['POST'])
def approve_payment(payment_id):
    payment = PendingPayment.query\
        .get_or_404(payment_id)

    if payment.status != 'pending':
        return jsonify(
            {"error": "Already reviewed"}), 400

    payment.status      = 'approved'
    payment.reviewed_at = datetime.utcnow()

    user = User.query.get(payment.user_id)
    if user:
        user.gold_coins = (
            user.gold_coins or 0) \
            + payment.gold_coins

    db.session.commit()

    return redirect(url_for('admin_panel'))


@app.route('/admin/reject_payment'
           '/<int:payment_id>',
           methods=['POST'])
def reject_payment(payment_id):
    payment = PendingPayment.query\
        .get_or_404(payment_id)

    if payment.status != 'pending':
        return jsonify(
            {"error": "Already reviewed"}), 400

    payment.status      = 'rejected'
    payment.reviewed_at = datetime.utcnow()
    db.session.commit()

    return redirect(url_for('admin_panel'))


@app.route('/admin/complete_withdrawal'
           '/<int:withdraw_id>',
           methods=['POST'])
def complete_withdrawal(withdraw_id):
    withdraw = WithdrawRequest.query\
        .get_or_404(withdraw_id)

    if withdraw.status != 'pending':
        return jsonify(
            {"error": "Already processed"}), 400

    note = request.form.get('note', '')

    withdraw.status       = 'completed'
    withdraw.completed_at = datetime.utcnow()
    withdraw.admin_note   = note
    db.session.commit()

    return redirect(url_for('admin_panel'))


@app.route('/admin/reject_withdrawal'
           '/<int:withdraw_id>',
           methods=['POST'])
def reject_withdrawal(withdraw_id):
    withdraw = WithdrawRequest.query\
        .get_or_404(withdraw_id)

    if withdraw.status != 'pending':
        return jsonify(
            {"error": "Already processed"}), 400

    note = request.form.get('note', '')

    # refund gold to user
    user = User.query.get(withdraw.user_id)
    if user:
        user.gold_coins = (
            user.gold_coins or 0) \
            + withdraw.gold_amount

    withdraw.status       = 'rejected'
    withdraw.completed_at = datetime.utcnow()
    withdraw.admin_note   = note
    db.session.commit()

    return redirect(url_for('admin_panel'))


# ═══════════════════════════════════════════
# API LISTS FOR ADMIN (JSON)
# ═══════════════════════════════════════════
@app.route('/admin/pending_payments',
           methods=['GET'])
def pending_payments():
    payments = PendingPayment.query\
        .filter_by(status='pending')\
        .order_by(PendingPayment.created_at
                  .desc()).all()
    return jsonify({
        "payments": [p.to_dict()
                     for p in payments],
        "count":    len(payments)
    }), 200


@app.route('/admin/pending_withdrawals',
           methods=['GET'])
def pending_withdrawals():
    withdrawals = WithdrawRequest.query\
        .filter_by(status='pending')\
        .order_by(WithdrawRequest.created_at
                  .desc()).all()
    return jsonify({
        "withdrawals": [w.to_dict()
                        for w in withdrawals],
        "count":       len(withdrawals)
    }), 200


# ═══════════════════════════════════════════
# CRYPTOMUS TEST ROUTES (kept for reference)
# ═══════════════════════════════════════════
@app.route('/api/crypto/balance',
           methods=['GET'])
def crypto_balance():
    result = call_cryptomus(
        'balance', {}, PAYMENT_KEY)
    return jsonify(result)


@app.route('/api/crypto/webhook',
           methods=['POST'])
def receive_webhook():
    data = request.json
    print('\n=== WEBHOOK ===')
    print(json.dumps(data, indent=2))

    if not data:
        return jsonify(
            {"error": "No data"}), 400

    received_sign = data.pop('sign', None)
    expected_sign = make_sign(
        data, PAYMENT_KEY)

    if received_sign != expected_sign:
        return jsonify(
            {"error": "Invalid signature"}
        ), 403

    return jsonify({"status": "ok"}), 200


# ═══════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )