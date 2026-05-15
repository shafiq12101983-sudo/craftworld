from flask import Flask, request, jsonify, render_template, url_for

from config import Config
import os
import hashlib
import json
import base64
import time
import requests
from werkzeug.utils import secure_filename
from werkzeug.utils import redirect
from flask import send_from_directory
from models import db, User, Stake
from datetime import datetime


app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
UPLOAD_FOLDER      = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── CRYPTOMUS KEYS ──
MERCHANT_UUID = '91beea2a-7df8-496c-b662-087ee10e5caa'
PAYMENT_KEY   = '35d7eea1b7e088ee2784ff199af823cdf190fd0b'
PAYOUT_KEY    = 'sgO0zQzV6jBCH3gJat0JChhAjUZlSm0kZCCBvqRX0JziWUmLC0UqBoI6iO8lsKvw5nDSQesAS8g1m2arnL4VxtB94T1bBelScvmIzIet8MAS6ErRMDel2Q3UUUDpz5Wh'

# ── VETHER CONVERSION ──
# Vether coins earned per $1 in game
VETHER_PER_USD = 500

# Vether coins needed to withdraw $1
# 20% worse rate than earning rate
VETHER_WITHDRAW_RATE = 600

# Minimum withdrawal — $5 USD equivalent
MIN_WITHDRAW_VETHER = 3_000

# ── MINERAL COIN RATES PER LEVEL ──
# How many mineral coins = $1 USD per level
# Starts at 15000 for Iron, decreases each level
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

# Buy rate is 80% of exchange rate
# so playing is always more efficient than buying
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
    """Generate Cryptomus MD5 signature"""
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
    """Make authenticated request to Cryptomus"""
    sign = make_sign(data, api_key)
    headers = {
        'merchant': MERCHANT_UUID,
        'sign':     sign,
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
    # Accepting JSON or Form data
    data = request.get_json() if request.is_json else request.form

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    phone = data.get("phone")

    if not name or not email:
        return jsonify({"error": "Name and Email are required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already exists"}), 409

    # Create user with is_approved=False and no image yet
    user = User(
        name=name,
        email=email,
        password=password,
        phone=phone,
        is_approved=False
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({
        "message": "Account created. Please verify your identity to enable withdrawals.",
        "user_id": user.id
    }), 201


@app.route('/api/verify', methods=['POST'])
def verify_user():
    player_id = request.form.get("player_id")

    if not player_id:
        return jsonify({"error": "Player ID required"}), 400

    user = User.query.get(player_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Handle multiple files
    selfie_file = request.files.get("selfie")
    id_file = request.files.get("id_doc")

    if not selfie_file or not id_file:
        return jsonify({"error": "Both selfie and ID document are required"}), 400

    if allowed_file(selfie_file.filename) and allowed_file(id_file.filename):
        # Save Selfie
        s_filename = secure_filename(f"selfie_{player_id}_{selfie_file.filename}")
        selfie_file.save(os.path.join(app.config["UPLOAD_FOLDER"], s_filename))

        # Save ID
        id_filename = secure_filename(f"id_{player_id}_{id_file.filename}")
        id_file.save(os.path.join(app.config["UPLOAD_FOLDER"], id_filename))

        # Update User Record
        user.image = s_filename  # Using existing image field for selfie
        user.id_image = id_filename  # You'll need to add this column to your User model
        db.session.commit()

        return jsonify({"message": "Verification documents uploaded successfully"}), 200

    return jsonify({"error": "Invalid file format"}), 400

@app.route('/api/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify(
            [u.to_dict() for u in users]), 200

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            filename)

@app.route('/admin')
def admin_panel():
    users = User.query.all()
    return render_template(
            'adminpanel.html', users=users)

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

# ═══════════════════════════════════════════
# CRYPTOMUS TEST ROUTES
# ═══════════════════════════════════════════
@app.route('/api/crypto/balance',
           methods=['GET'])
def crypto_balance():
    """
    Test — check API keys are working.
    Call: GET /api/crypto/balance
    """
    result = call_cryptomus(
            'balance', {}, PAYMENT_KEY)
    return jsonify(result)

@app.route('/api/crypto/test-payment',
           methods=['GET'])
def test_payment():
    """
    Test — creates a payment URL.
    Call: GET /api/crypto/test-payment
    """
    data = {
        'amount':       '1',
        'currency':     'USD',
        'order_id':     f'test_{int(time.time())}',
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook'
    }
    result = call_cryptomus(
            'payment', data, PAYMENT_KEY)
    return jsonify(result)

@app.route('/api/crypto/test-webhook',
           methods=['GET'])
def test_webhook():
    """
    Test — simulates a payment webhook.
    Call: GET /api/crypto/test-webhook
    """
    data = {
        'currency':     'USDT',
        'network':      'tron',
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook',
        'status':       'paid'
    }
    result = call_cryptomus(
            'test-webhook/payment',
            data, PAYMENT_KEY)
    return jsonify(result)

@app.route('/api/crypto/test-payout-webhook',
           methods=['GET'])
def test_payout_webhook():
    """
    Test — simulates a payout webhook.
    Call: GET /api/crypto/test-payout-webhook
    """
    data = {
        'currency':     'USDT',
        'network':      'tron',
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook',
        'status':       'paid'
    }
    result = call_cryptomus(
            'test-webhook/payout',
            data, PAYOUT_KEY)
    return jsonify(result)

# ═══════════════════════════════════════════
# BUY COINS
# ═══════════════════════════════════════════
@app.route('/api/crypto/buy',
           methods=['POST'])
def buy_coins():
    """
    Called by Android when player buys coins.

    Required JSON body:
    {
        "player_id":     "123",
        "mineral_level": 0,
        "usd_amount":    "1.00"
    }

    Server calculates vether equivalent
    and creates Cryptomus payment.
    """
    body = request.json

    if not body:
        return jsonify(
                {"error": "No data provided"}
                ), 400

    player_id     = body.get('player_id')
    mineral_level = int(body.get(
            'mineral_level', 0))
    usd_amount_str = str(body.get(
            'usd_amount', '0'))

    # ── VALIDATE ──
    if not player_id:
        return jsonify(
                {"error": "Player ID required"}
                ), 400

    try:
        player_id_int = int(player_id)
        usd_float     = float(usd_amount_str)
    except (ValueError, TypeError):
        return jsonify(
                {"error": "Invalid data"}
                ), 400

    if usd_float <= 0:
        return jsonify(
                {"error": "Invalid amount"}
                ), 400

    # ── CHECK PLAYER EXISTS ──
    user = User.query.filter_by(
            id=player_id_int).first()
    if not user:
        return jsonify(
                {"error": "Player not found"}
                ), 404

    # ── CALCULATE VETHER EQUIVALENT ──
    # use clamped level index
    lv_idx = min(max(mineral_level, 0), 9)

    # how many mineral coins player gets
    mineral_coins = int(
            BUY_COINS_PER_USD[lv_idx]
            * usd_float)

    # convert to vether equivalent for storage
    # mineral coins / COINS_PER_USD[lv] * VETHER_PER_USD
    vether_equivalent = int(
            (mineral_coins
             / COINS_PER_USD[lv_idx])
            * VETHER_PER_USD)

    # ── CREATE ORDER ID ──
    # format: payment_PLAYERID_VETHERCOINS_TIMESTAMP
    order_id = (f"payment_{player_id_int}"
                f"_{vether_equivalent}"
                f"_{int(time.time())}")

    # ── CREATE CRYPTOMUS PAYMENT ──
    payment_data = {
        'amount':       usd_amount_str,
        'currency':     'USD',
        'order_id':     order_id,
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook',
        'url_success':
            'http://localhost:5000'
            '/api/crypto/payment-success',
        'url_return':
            'http://localhost:5000'
            '/api/crypto/payment-cancel'
    }

    result = call_cryptomus(
            'payment', payment_data,
            PAYMENT_KEY)

    print(f'\nBuy coins for '
          f'player {player_id_int}:')
    print(f'Level: {lv_idx}')
    print(f'USD: {usd_amount_str}')
    print(f'Mineral coins: {mineral_coins}')
    print(f'Vether equivalent: '
          f'{vether_equivalent}')
    print(json.dumps(result, indent=2))

    if 'error' in result:
        return jsonify({
            "error":  "Payment creation failed",
            "detail": result
        }), 500

    payment_url  = result.get(
            'result', {}).get('url')
    payment_uuid = result.get(
            'result', {}).get('uuid')

    return jsonify({
        "message":           "Payment created",
        "order_id":          order_id,
        "payment_url":       payment_url,
        "payment_uuid":      payment_uuid,
        "mineral_coins":     mineral_coins,
        "vether_equivalent": vether_equivalent,
        "usd_amount":        usd_amount_str,
        "status":            "pending"
    }), 200


# ── PAYMENT SUCCESS PAGE ──
@app.route('/api/crypto/payment-success',
           methods=['GET'])
def payment_success():
    return jsonify({
        "status":  "success",
        "message": "Payment received. "
                   "Coins will be credited shortly."
    }), 200


# ── PAYMENT CANCEL PAGE ──
@app.route('/api/crypto/payment-cancel',
           methods=['GET'])
def payment_cancel():
    return jsonify({
        "status":  "cancelled",
        "message": "Payment was cancelled."
    }), 200


# ═══════════════════════════════════════════
# WITHDRAWAL
# ═══════════════════════════════════════════
@app.route('/api/crypto/withdraw',
           methods=['POST'])
def withdraw():
    """
    Called by Android when player
    wants to withdraw coins as USDT.

    Required JSON body:
    {
        "player_id":      "123",
        "wallet_address": "TXxxx...",
        "coin_amount":    15000,
        "mineral_level":  0,
        "network":        "tron"
    }
    """
    body = request.json

    if not body:
        return jsonify(
                {"error": "No data provided"}
                ), 400

    player_id      = body.get('player_id')
    wallet_address = body.get('wallet_address')
    coin_amount    = body.get('coin_amount', 0)
    mineral_level  = int(body.get(
            'mineral_level', 0))
    network        = body.get('network', 'tron')

    # ── VALIDATE ──
    if not player_id:
        return jsonify(
                {"error": "Player ID required"}
                ), 400

    if not wallet_address:
        return jsonify(
                {"error": "Wallet address required"}
                ), 400

    if coin_amount <= 0:
        return jsonify(
                {"error": "Invalid coin amount"}
                ), 400

    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
                {"error": "Invalid player ID"}
                ), 400

    # ── CHECK PLAYER EXISTS ──
    user = User.query.filter_by(
            id=player_id_int).first()
    if not user:
        return jsonify(
                {"error": "Player not found"}
                ), 404

    # ── CHECK KYC APPROVED ──
    if not user.is_approved:
        return jsonify({
            "error": "Account not verified. "
                     "Please complete KYC first."
        }), 403

    # ── CONVERT COINS TO USD ──
    lv_idx = min(max(mineral_level, 0), 9)
    coins_per_dollar = COINS_PER_USD[lv_idx]
    usd_amount = round(
            coin_amount / coins_per_dollar, 2)

    if usd_amount < 1:
        pence = int(usd_amount * 100)
        return jsonify({
            "error": f"Minimum withdrawal is "
                     f"$1 USD. Your balance is "
                     f"worth {pence}¢"
        }), 400

    # ── ALSO VALIDATE VETHER BALANCE ──
    # convert usd to vether for server record
    vether_equivalent = int(
            usd_amount * VETHER_WITHDRAW_RATE)

    if user.vether_balance < vether_equivalent:
        return jsonify({
            "error": "Insufficient balance "
                     "on server record"
        }), 400

    # ── CREATE ORDER ID ──
    order_id = (f"withdraw_{player_id_int}"
                f"_{vether_equivalent}"
                f"_{int(time.time())}")

    # ── CALL CRYPTOMUS PAYOUT ──
    payout_data = {
        'amount':       str(usd_amount),
        'currency':     'USD',
        'network':      network,
        'order_id':     order_id,
        'address':      wallet_address,
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook'
    }

    result = call_cryptomus(
            'payout', payout_data, PAYOUT_KEY)

    print(f'\nWithdrawal for '
          f'player {player_id_int}:')
    print(f'Coins: {coin_amount} '
          f'at level {lv_idx}')
    print(f'USD: {usd_amount}')
    print(json.dumps(result, indent=2))

    if 'error' in result:
        return jsonify({
            "error":  "Payout failed",
            "detail": result
        }), 500

    payout_uuid = result.get(
            'result', {}).get('uuid')

    return jsonify({
        "message":     "Withdrawal submitted",
        "order_id":    order_id,
        "payout_uuid": payout_uuid,
        "usd_amount":  usd_amount,
        "coin_amount": coin_amount,
        "status":      "processing"
    }), 200


# ═══════════════════════════════════════════
# WEBHOOK — receives all Cryptomus callbacks
# ═══════════════════════════════════════════
@app.route('/api/crypto/webhook',
           methods=['POST'])
def receive_webhook():
    """
    Cryptomus calls this when payment
    or payout status changes.
    """
    data = request.json

    print('\n=== WEBHOOK RECEIVED ===')
    print(json.dumps(data, indent=2))

    if not data:
        return jsonify(
                {"error": "No data"}), 400

    # ── VERIFY SIGNATURE ──
    received_sign = data.pop('sign', None)
    expected_sign = make_sign(
            data, PAYMENT_KEY)

    if received_sign != expected_sign:
        print('Invalid signature!')
        return jsonify(
                {"error": "Invalid signature"}
                ), 403

    status   = data.get('status')
    order_id = data.get('order_id', '')
    amount   = data.get('amount')

    print(f'Status:   {status}')
    print(f'Order ID: {order_id}')
    print(f'Amount:   {amount}')

    # ── HANDLE PAYOUT CONFIRMED ──
    # order format: withdraw_PLAYERID_VETHER_TIMESTAMP
    if status == 'paid' and \
            order_id.startswith('withdraw_'):

        parts = order_id.split('_')

        # need at least 4 parts
        # withdraw / playerid / vether / timestamp
        if len(parts) >= 4:
            try:
                player_id_int   = int(parts[1])
                vether_deduct   = int(parts[2])
            except (ValueError, TypeError):
                print(f'Invalid withdraw '
                      f'order: {order_id}')
                return jsonify(
                        {"status": "ok"}), 200

            user = User.query.filter_by(
                    id=player_id_int).first()

            if user:
                if user.vether_balance \
                        >= vether_deduct:
                    user.vether_balance \
                            -= vether_deduct
                    db.session.commit()
                    print(
                        f'Payout confirmed — '
                        f'player {player_id_int} '
                        f'deducted '
                        f'{vether_deduct} Vether')
                else:
                    print(
                        f'Warning: player '
                        f'{player_id_int} '
                        f'insufficient balance '
                        f'for deduction')
            else:
                print(f'Player {player_id_int} '
                      f'not found')
        else:
            print(f'Invalid withdraw order '
                  f'format: {order_id}')

    # ── HANDLE PAYMENT RECEIVED ──
    # order format: payment_PLAYERID_VETHER_TIMESTAMP
    elif status == 'paid' and \
            order_id.startswith('payment_'):

        parts = order_id.split('_')

        # need at least 4 parts
        # payment / playerid / vether / timestamp
        if len(parts) >= 4:
            try:
                player_id_int    = int(parts[1])
                vether_to_credit = int(parts[2])
            except (ValueError, TypeError):
                print(f'Invalid payment '
                      f'order: {order_id}')
                return jsonify(
                        {"status": "ok"}), 200

            user = User.query.filter_by(
                    id=player_id_int).first()

            if user:
                user.vether_balance \
                        += vether_to_credit
                db.session.commit()
                print(
                    f'Payment confirmed — '
                    f'player {player_id_int} '
                    f'credited '
                    f'{vether_to_credit} Vether')
            else:
                print(f'Player {player_id_int} '
                      f'not found')
        else:
            print(f'Invalid payment order '
                  f'format: {order_id}')

    # ── HANDLE FAILED ──
    elif status in ['fail', 'system_fail',
                    'cancel']:
        print(f'Transaction failed: {status}')
        print(f'Order: {order_id}')

    # always return 200 to Cryptomus
    return jsonify({"status": "ok"}), 200


# ═══════════════════════════════════════════
# CHECK STATUS
# ═══════════════════════════════════════════
@app.route('/api/crypto/status/<order_id>',
           methods=['GET'])
def check_status(order_id):
    """
    Android polls this to check
    if withdrawal is complete.
    Call: GET /api/crypto/status/withdraw_123_456_789
    """
    # use payout/info for withdrawals
    # use payment/info for purchases
    if order_id.startswith('withdraw_'):
        data   = {'order_id': order_id}
        result = call_cryptomus(
                'payout/info', data, PAYOUT_KEY)
    else:
        data   = {'order_id': order_id}
        result = call_cryptomus(
                'payment/info', data, PAYMENT_KEY)

    return jsonify(result)


# ── STAKE COINS ──
@app.route('/api/stake/create',
           methods=['POST'])
def create_stake():
    """
    Player stakes crypto.
    Required JSON:
    {
        "player_id": "123",
        "currency": "USDT",
        "amount": 10.00,
        "wallet_address": "TXxxx..."
    }
    """
    body = request.json
    if not body:
        return jsonify(
                {"error": "No data"}), 400

    player_id      = body.get('player_id')
    currency       = body.get('currency',
                               'USDT')
    amount         = body.get('amount', 0)
    wallet_address = body.get(
                        'wallet_address', '')

    # validate
    if not player_id:
        return jsonify(
                {"error": "Player ID required"}
                ), 400

    if currency not in ['USDT', 'BTC']:
        return jsonify(
                {"error": "Currency must be "
                           "USDT or BTC"}), 400

    if amount < 5:
        return jsonify(
                {"error": "Minimum stake "
                           "is $5"}), 400

    if not wallet_address:
        return jsonify(
                {"error": "Wallet address "
                           "required"}), 400

    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
                {"error": "Invalid player ID"}
                ), 400

    user = User.query.filter_by(
            id=player_id_int).first()
    if not user:
        return jsonify(
                {"error": "Player not found"}
                ), 404

    if not user.is_approved:
        return jsonify(
                {"error": "Account not verified"}
                ), 403

    # check max 3 active stakes
    active_stakes = Stake.query.filter_by(
            user_id=player_id_int,
            status='active').count()
    if active_stakes >= 3:
        return jsonify(
                {"error": "Maximum 3 active "
                           "stakes allowed"}), 400

    # save wallet
    if currency == 'USDT':
        user.usdt_wallet = wallet_address
    else:
        user.btc_wallet = wallet_address

    # create stake record
    stake = Stake(
            user_id=player_id_int,
            currency=currency,
            amount=float(amount))
    db.session.add(stake)
    db.session.commit()

    print(f'\nStake created: '
          f'Player {player_id_int} '
          f'staked {amount} {currency}')

    return jsonify({
        "message":    "Stake created",
        "stake":      stake.to_dict(),
        "end_time":   str(stake.end_time),
        "profit":     stake.profit_amount(),
        "payout":     stake.payout_amount()
    }), 200


# ── GET PLAYER STAKES ──
@app.route('/api/stake/list/<player_id>',
           methods=['GET'])
def get_stakes(player_id):
    """
    Get all stakes for player.
    Call: GET /api/stake/list/123
    """
    try:
        player_id_int = int(player_id)
    except (ValueError, TypeError):
        return jsonify(
                {"error": "Invalid player ID"}
                ), 400

    stakes = Stake.query.filter_by(
            user_id=player_id_int).order_by(
            Stake.start_time.desc()).all()

    return jsonify({
        "stakes":       [s.to_dict()
                         for s in stakes],
        "active_count": sum(
                1 for s in stakes
                if s.status == 'active'),
        "total_staked": sum(
                s.amount for s in stakes
                if s.status == 'active')
    }), 200


# ── CLAIM MATURED STAKE ──
@app.route('/api/stake/claim',
           methods=['POST'])
def claim_stake():
    """
    Claim matured stake (7 days passed).
    Required JSON:
    {
        "player_id": "123",
        "stake_id": 1
    }
    """
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
            id=stake_id_int,
            user_id=player_id_int,
            status='active').first()

    if not stake:
        return jsonify(
                {"error": "Stake not found"}
                ), 404

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
                {"error": "Player not found"}
                ), 404

    # get wallet
    wallet = (user.usdt_wallet
              if stake.currency == 'USDT'
              else user.btc_wallet)

    if not wallet:
        return jsonify(
                {"error": "No wallet address"}
                ), 400

    payout = stake.payout_amount()

    # call Cryptomus payout
    order_id = (f"stake_claim_"
                f"{player_id_int}_"
                f"{stake_id_int}_"
                f"{int(time.time())}")

    payout_data = {
        'amount':       str(payout),
        'currency':     stake.currency,
        'network':      'tron'
                        if stake.currency == 'USDT'
                        else 'btc',
        'order_id':     order_id,
        'address':      wallet,
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook'
    }

    result = call_cryptomus(
            'payout', payout_data, PAYOUT_KEY)

    if 'error' in result:
        return jsonify({
            "error":  "Payout failed",
            "detail": result
        }), 500

    # mark stake complete
    stake.status  = 'completed'
    stake.tx_hash = result.get(
            'result', {}).get('uuid', '')
    db.session.commit()

    print(f'\nStake claimed: '
          f'Player {player_id_int} '
          f'received {payout} '
          f'{stake.currency}')

    return jsonify({
        "message":  "Stake claimed",
        "payout":   payout,
        "currency": stake.currency,
        "profit":   stake.profit_amount(),
        "order_id": order_id
    }), 200


# ── EARLY UNSTAKE ──
@app.route('/api/stake/unstake',
           methods=['POST'])
def unstake():
    """
    Early unstake — lose 5% penalty.
    Required JSON:
    {
        "player_id": "123",
        "stake_id": 1
    }
    """
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
            id=stake_id_int,
            user_id=player_id_int,
            status='active').first()

    if not stake:
        return jsonify(
                {"error": "Stake not found"}
                ), 404

    # if already matured just claim normally
    if stake.is_matured():
        return jsonify({
            "error": "Stake matured — "
                     "use /claim instead"
        }), 400

    user = User.query.filter_by(
            id=player_id_int).first()
    if not user:
        return jsonify(
                {"error": "Player not found"}
                ), 404

    wallet = (user.usdt_wallet
              if stake.currency == 'USDT'
              else user.btc_wallet)

    if not wallet:
        return jsonify(
                {"error": "No wallet address"}
                ), 400

    early_payout = stake.early_payout_amount()
    penalty      = stake.penalty_amount()

    # call Cryptomus payout
    order_id = (f"stake_unstake_"
                f"{player_id_int}_"
                f"{stake_id_int}_"
                f"{int(time.time())}")

    payout_data = {
        'amount':       str(early_payout),
        'currency':     stake.currency,
        'network':      'tron'
                        if stake.currency == 'USDT'
                        else 'btc',
        'order_id':     order_id,
        'address':      wallet,
        'url_callback':
            'http://localhost:5000'
            '/api/crypto/webhook'
    }

    result = call_cryptomus(
            'payout', payout_data, PAYOUT_KEY)

    if 'error' in result:
        return jsonify({
            "error":  "Payout failed",
            "detail": result
        }), 500

    # mark cancelled
    stake.status  = 'cancelled'
    stake.tx_hash = result.get(
            'result', {}).get('uuid', '')
    db.session.commit()

    print(f'\nEarly unstake: '
          f'Player {player_id_int} '
          f'received {early_payout} '
          f'{stake.currency} '
          f'(penalty: {penalty})')

    return jsonify({
        "message":       "Unstaked early",
        "payout":        early_payout,
        "penalty":       penalty,
        "currency":      stake.currency,
        "order_id":      order_id
    }), 200

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True)