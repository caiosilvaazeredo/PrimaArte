# -*- coding: utf-8 -*-
"""
VAL'S - LUXURY HANDCRAFTED
===========================
Colecao Riviera Botanica
Aplicacao principal com pagamentos Asaas, area do cliente e seguranca
"""

from flask import (Flask, render_template, request, jsonify, session,
                   redirect, url_for, flash, abort, make_response, g)
import json
import os
import re
import unicodedata
import urllib.parse
import hmac
import hashlib
import math
import random
import string
from datetime import datetime, timedelta
import uuid
from werkzeug.utils import secure_filename
from functools import wraps

import bcrypt
import pyotp
import qrcode
import qrcode.image.svg
import requests as http_requests
from io import BytesIO
import base64

from dotenv import load_dotenv

load_dotenv()

import email_service
import shipping_service

# ================================
# FIREBASE FIRESTORE
# ================================
import firebase_admin
from firebase_admin import credentials, firestore as firebase_firestore

FIREBASE_CRED_FILE = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')
USE_FIREBASE = False
db = None

if os.path.exists(FIREBASE_CRED_FILE):
    try:
        cred = credentials.Certificate(FIREBASE_CRED_FILE)
        firebase_admin.initialize_app(cred)
        db = firebase_firestore.client()
        USE_FIREBASE = True
        print(f"[Firebase] Conectado ao Firestore com sucesso!")
    except Exception as e:
        print(f"[Firebase] Erro ao conectar: {e}. Usando JSON como fallback.")
else:
    print(f"[Firebase] Arquivo {FIREBASE_CRED_FILE} nao encontrado. Usando JSON como fallback.")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'vals-luxury-secret-key-2025')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

# ================================
# CONFIGURACOES
# ================================
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '+5521973108293')
INSTAGRAM_URL = os.environ.get('INSTAGRAM_URL', 'https://www.instagram.com/primaarte2025/')
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

ASAAS_API_KEY = os.environ.get('ASAAS_API_KEY', '')
ASAAS_ENV = os.environ.get('ASAAS_ENVIRONMENT', 'sandbox')
ASAAS_BASE_URL = (
    'https://api.asaas.com/v3' if ASAAS_ENV == 'production'
    else 'https://sandbox.asaas.com/api/v3'
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATA_FILE = 'data.json'

# ================================
# RATE LIMITING (simple in-memory)
# ================================
_rate_limit_store = {}

def check_rate_limit(key, max_requests=5, window_seconds=60):
    """Simple rate limiter. Returns True if allowed, False if rate limited."""
    now = datetime.now()
    if key not in _rate_limit_store:
        _rate_limit_store[key] = []

    # Clean old entries
    _rate_limit_store[key] = [
        t for t in _rate_limit_store[key]
        if (now - t).total_seconds() < window_seconds
    ]

    if len(_rate_limit_store[key]) >= max_requests:
        return False

    _rate_limit_store[key].append(now)
    return True


# ================================
# CSRF PROTECTION
# ================================
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets_token()
    return session['_csrf_token']

def secrets_token():
    return ''.join(random.SystemRandom().choices(
        string.ascii_letters + string.digits, k=64
    ))

app.jinja_env.globals['csrf_token'] = generate_csrf_token

@app.before_request
def csrf_protect():
    if request.method == 'POST':
        # Skip CSRF for API webhooks
        if request.path.startswith('/api/webhook'):
            return
        token = session.get('_csrf_token')
        form_token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != form_token:
            abort(403)


# ================================
# CAPTCHA (math-based)
# ================================
def generate_captcha():
    a = random.randint(2, 15)
    b = random.randint(1, 10)
    session['captcha_answer'] = str(a + b)
    return f"{a} + {b}"

def verify_captcha(answer):
    expected = session.pop('captcha_answer', None)
    return expected and str(answer).strip() == expected

app.jinja_env.globals['generate_captcha'] = generate_captcha


# ================================
# DATA LAYER (Firebase Firestore + JSON fallback)
# ================================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Firebase Firestore helpers ---
def _fb_get_collection(collection_name):
    """Get all documents from a Firestore collection."""
    docs = db.collection(collection_name).stream()
    items = []
    for doc in docs:
        item = doc.to_dict()
        item['id'] = doc.id
        items.append(item)
    return items

def _fb_get_doc(collection_name, doc_id):
    """Get a single document from Firestore."""
    doc = db.collection(collection_name).document(doc_id).get()
    if doc.exists:
        item = doc.to_dict()
        item['id'] = doc.id
        return item
    return None

def _fb_save_doc(collection_name, doc_id, data_dict):
    """Save a document to Firestore."""
    db.collection(collection_name).document(doc_id).set(data_dict)

def _fb_delete_doc(collection_name, doc_id):
    """Delete a document from Firestore."""
    db.collection(collection_name).document(doc_id).delete()


def load_data():
    """Load all data. Uses Firebase if available, JSON otherwise."""
    if USE_FIREBASE:
        return {
            'products': _fb_get_collection('products'),
            'announcements': _fb_get_collection('announcements'),
            'customers': _fb_get_collection('customers'),
            'orders': _fb_get_collection('orders'),
            'admin_password': os.environ.get('ADMIN_PASSWORD', 'primaarte2025')
        }

    # JSON fallback
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data.setdefault('products', [])
            data.setdefault('announcements', [])
            data.setdefault('customers', [])
            data.setdefault('orders', [])
            data.setdefault('admin_password', 'primaarte2025')
            return data
    return {
        'products': [],
        'announcements': [],
        'customers': [],
        'orders': [],
        'admin_password': 'primaarte2025'
    }

def save_data(data):
    """Save all data. Uses Firebase if available, JSON otherwise."""
    if USE_FIREBASE:
        # Firebase saves happen per-document, this is only for JSON fallback
        # For Firebase, use save_item() instead
        return
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_item(collection_name, item_id, item_data):
    """Save a single item to the correct storage."""
    if USE_FIREBASE:
        save_dict = {k: v for k, v in item_data.items() if k != 'id'}
        _fb_save_doc(collection_name, item_id, save_dict)
    else:
        data = load_data()
        items = data.get(collection_name, [])
        existing_index = next((i for i, x in enumerate(items) if x.get('id') == item_id), None)
        if existing_index is not None:
            items[existing_index] = item_data
        else:
            items.append(item_data)
        data[collection_name] = items
        save_data(data)

def delete_item(collection_name, item_id):
    """Delete a single item from the correct storage."""
    if USE_FIREBASE:
        _fb_delete_doc(collection_name, item_id)
    else:
        data = load_data()
        data[collection_name] = [x for x in data.get(collection_name, []) if x.get('id') != item_id]
        save_data(data)

def get_item(collection_name, item_id):
    """Get a single item from the correct storage."""
    if USE_FIREBASE:
        return _fb_get_doc(collection_name, item_id)
    data = load_data()
    return next((x for x in data.get(collection_name, []) if x.get('id') == item_id), None)


# ================================
# AUTH DECORATORS
# ================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('customer_id'):
            flash('Faca login para acessar esta pagina.', 'info')
            return redirect(url_for('customer_login'))
        return f(*args, **kwargs)
    return decorated_function


# ================================
# HELPERS
# ================================
def create_slug(text):
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')

def get_product_current_price(product):
    if product.get('promotion_active') and product.get('promotional_price'):
        return product['promotional_price']
    return product['price']

def calculate_discount_percentage(regular_price, promotional_price):
    if not promotional_price or promotional_price >= regular_price:
        return 0
    return round(((regular_price - promotional_price) / regular_price) * 100)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def get_customer(customer_id):
    return get_item('customers', customer_id)

def generate_order_number():
    return f"VLS-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"


# ================================
# TEMPLATE FILTERS & GLOBALS
# ================================
@app.template_filter('slug')
def slug_filter(text):
    return create_slug(text)

@app.template_filter('calculate_discount')
def calculate_discount_filter(regular_price, promotional_price):
    return calculate_discount_percentage(regular_price, promotional_price)

@app.template_global()
def get_current_price(product):
    return get_product_current_price(product)

@app.template_global()
def product_url(product):
    return url_for('product_detail', product_slug=create_slug(product['name']))

@app.context_processor
def inject_globals():
    customer = None
    if session.get('customer_id'):
        customer = get_customer(session['customer_id'])
    return {
        'current_customer': customer,
        'cart_count': len(session.get('cart', []))
    }


# ================================
# ASAAS PAYMENT API
# ================================
class AsaasAPI:
    """Wrapper for the Asaas payment gateway API."""

    def __init__(self):
        self.base_url = ASAAS_BASE_URL
        self.headers = {
            'Content-Type': 'application/json',
            'access_token': ASAAS_API_KEY
        }

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}/{endpoint}"
        try:
            resp = http_requests.request(
                method, url, headers=self.headers, json=data, timeout=30
            )
            return resp.json(), resp.status_code
        except Exception as e:
            return {'error': str(e)}, 500

    def create_customer(self, name, email, cpf_cnpj, phone=None):
        """Create or find customer in Asaas."""
        payload = {
            'name': name,
            'email': email,
            'cpfCnpj': cpf_cnpj,
        }
        if phone:
            payload['phone'] = phone
        return self._request('POST', 'customers', payload)

    def create_payment(self, customer_id, value, billing_type, description,
                       due_date=None, installment_count=None):
        """
        Create a payment.
        billing_type: BOLETO, CREDIT_CARD, CREDIT_CARD (debit via Asaas), PIX
        """
        if not due_date:
            due_date = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')

        payload = {
            'customer': customer_id,
            'billingType': billing_type,
            'value': value,
            'dueDate': due_date,
            'description': description,
        }

        if billing_type == 'CREDIT_CARD' and installment_count and installment_count > 1:
            payload['installmentCount'] = installment_count
            payload['installmentValue'] = round(value / installment_count, 2)

        return self._request('POST', 'payments', payload)

    def get_payment(self, payment_id):
        return self._request('GET', f'payments/{payment_id}')

    def get_pix_qrcode(self, payment_id):
        return self._request('GET', f'payments/{payment_id}/pixQrCode')

    def get_boleto_url(self, payment_id):
        return self._request('GET', f'payments/{payment_id}/identificationField')

    def pay_with_credit_card(self, payment_id, card_data, holder_info):
        """Process credit card payment."""
        payload = {
            'creditCard': card_data,
            'creditCardHolderInfo': holder_info
        }
        return self._request('POST', f'payments/{payment_id}/payWithCreditCard', payload)


asaas = AsaasAPI()


# ================================
# MAIN ROUTES
# ================================
@app.route('/')
def index():
    data = load_data()

    def _enrich(products):
        for p in products:
            p['current_price'] = get_product_current_price(p)
            if p.get('promotion_active') and p.get('promotional_price'):
                p['discount_percent'] = calculate_discount_percentage(
                    p['price'], p['promotional_price']
                )
        return products

    featured_products = _enrich([p for p in data['products'] if p.get('featured', False)][:6])
    unique_products = _enrich([p for p in data['products'] if p.get('is_unique', False)][:6])
    collection_products = _enrich([p for p in data['products'] if not p.get('is_unique', False)][:6])

    announcements = [a for a in data['announcements'] if a.get('active', True)][:3]
    return render_template('index.html',
                           featured_products=featured_products,
                           unique_products=unique_products,
                           collection_products=collection_products,
                           announcements=announcements)

@app.route('/produtos')
def products():
    data = load_data()
    category = request.args.get('categoria', '')
    tipo = request.args.get('tipo', '')  # 'unicas' or 'colecao'
    products_list = data['products']

    if category:
        products_list = [
            p for p in products_list
            if p.get('category', '').lower() == category.lower()
        ]

    if tipo == 'unicas':
        products_list = [p for p in products_list if p.get('is_unique', False)]
    elif tipo == 'colecao':
        products_list = [p for p in products_list if not p.get('is_unique', False)]

    for product in products_list:
        product['current_price'] = get_product_current_price(product)
        if product.get('promotion_active') and product.get('promotional_price'):
            product['discount_percent'] = calculate_discount_percentage(
                product['price'], product['promotional_price']
            )

    return render_template('products.html',
                           products=products_list,
                           current_category=category,
                           current_tipo=tipo)

@app.route('/produto/<product_slug>')
def product_detail(product_slug):
    data = load_data()

    product = None
    for p in data['products']:
        if create_slug(p['name']) == product_slug or p['id'] == product_slug:
            product = p
            break

    if not product:
        flash('Produto nao encontrado!', 'error')
        return redirect(url_for('products'))

    product['current_price'] = get_product_current_price(product)
    if product.get('promotion_active') and product.get('promotional_price'):
        product['discount_percent'] = calculate_discount_percentage(
            product['price'], product['promotional_price']
        )
        product['savings'] = product['price'] - product['promotional_price']

    return render_template('product.html', product=product)

@app.route('/sobre')
def about():
    return render_template('about.html')


# ================================
# CART
# ================================
@app.route('/carrinho')
def cart():
    cart_items = session.get('cart', [])
    data = load_data()

    detailed_cart = []
    total = 0

    for item in cart_items:
        product = next((p for p in data['products'] if p['id'] == item['product_id']), None)
        if product:
            current_price = get_product_current_price(product)
            item_total = current_price * item['quantity']
            detailed_cart.append({
                'id': item['product_id'],
                'name': product['name'],
                'price': current_price,
                'regular_price': product['price'],
                'promotional_price': product.get('promotional_price'),
                'promotion_active': product.get('promotion_active', False),
                'quantity': item['quantity'],
                'total': item_total,
                'images': product.get('images', []),
                'description': item.get('description', '')
            })
            total += item_total

    return render_template('cart.html', cart_items=detailed_cart, total=total)

@app.route('/adicionar-carrinho', methods=['POST'])
def add_to_cart():
    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))
    description = request.form.get('description', '')

    if 'cart' not in session:
        session['cart'] = []

    cart = session['cart']
    existing_item = next((item for item in cart if item['product_id'] == product_id), None)

    if existing_item:
        existing_item['quantity'] += quantity
    else:
        cart.append({
            'product_id': product_id,
            'quantity': quantity,
            'description': description
        })

    session['cart'] = cart
    flash('Produto adicionado ao carrinho!', 'success')
    return redirect(url_for('cart'))

@app.route('/remover-carrinho/<product_id>')
def remove_from_cart(product_id):
    if 'cart' in session:
        session['cart'] = [item for item in session['cart'] if item['product_id'] != product_id]
        flash('Produto removido do carrinho!', 'info')
    return redirect(url_for('cart'))


# ================================
# CHECKOUT & PAYMENT
# ================================
@app.route('/checkout', methods=['GET'])
def checkout_page():
    """Show checkout page with payment options."""
    cart_items = session.get('cart', [])
    if not cart_items:
        flash('Seu carrinho esta vazio!', 'error')
        return redirect(url_for('cart'))

    data = load_data()
    detailed_cart = []
    total = 0

    for item in cart_items:
        product = next((p for p in data['products'] if p['id'] == item['product_id']), None)
        if product:
            current_price = get_product_current_price(product)
            item_total = current_price * item['quantity']
            detailed_cart.append({
                'id': item['product_id'],
                'name': product['name'],
                'price': current_price,
                'quantity': item['quantity'],
                'total': item_total,
                'images': product.get('images', [])
            })
            total += item_total

    customer = None
    if session.get('customer_id'):
        customer = get_customer(session['customer_id'])

    return render_template('checkout.html',
                           cart_items=detailed_cart,
                           total=total,
                           customer=customer)

@app.route('/checkout/process', methods=['POST'])
def checkout_process():
    """Process payment through Asaas."""
    cart_items = session.get('cart', [])
    if not cart_items:
        flash('Seu carrinho esta vazio!', 'error')
        return redirect(url_for('cart'))

    if not check_rate_limit(f"checkout_{request.remote_addr}", 3, 60):
        flash('Muitas tentativas. Aguarde um momento.', 'error')
        return redirect(url_for('checkout_page'))

    data = load_data()
    payment_method = request.form.get('payment_method', 'PIX')

    # Calculate total
    total = 0
    order_items = []
    for item in cart_items:
        product = next((p for p in data['products'] if p['id'] == item['product_id']), None)
        if product:
            price = get_product_current_price(product)
            total += price * item['quantity']
            order_items.append({
                'product_id': item['product_id'],
                'name': product['name'],
                'price': price,
                'quantity': item['quantity'],
                'subtotal': price * item['quantity']
            })

    # Customer info
    customer_name = request.form.get('name', '').strip()
    customer_email = request.form.get('email', '').strip().lower()
    customer_cpf = re.sub(r'[^\d]', '', request.form.get('cpf', ''))
    customer_phone = request.form.get('phone', '').strip()

    # Auto-create guest customer by CPF (invisible to user)
    # If user later registers with same email, orders will already be linked
    guest_customer_id = session.get('customer_id')
    if not guest_customer_id and customer_cpf:
        data_all = load_data()
        # Search by CPF first, then by email
        existing = next(
            (c for c in data_all['customers'] if c.get('cpf') == customer_cpf),
            None
        )
        if not existing and customer_email:
            existing = next(
                (c for c in data_all['customers'] if c.get('email') == customer_email),
                None
            )

        if existing:
            guest_customer_id = existing['id']
            # Update name/phone if missing
            changed = False
            if not existing.get('name') and customer_name:
                existing['name'] = customer_name
                changed = True
            if not existing.get('phone') and customer_phone:
                existing['phone'] = customer_phone
                changed = True
            if changed:
                save_item('customers', existing['id'], existing)
        else:
            # Create ghost customer (no password = can't login until registers)
            guest_customer_id = str(uuid.uuid4())
            guest_customer = {
                'id': guest_customer_id,
                'name': customer_name,
                'email': customer_email,
                'cpf': customer_cpf,
                'phone': customer_phone,
                'password': '',
                'totp_secret': '',
                'totp_enabled': False,
                'is_guest': True,
                'created_at': datetime.now().isoformat()
            }
            save_item('customers', guest_customer_id, guest_customer)

    # Create or find Asaas customer
    asaas_customer_id = None
    if ASAAS_API_KEY and ASAAS_API_KEY != 'sua_chave_api_aqui':
        result, status = asaas.create_customer(
            customer_name, customer_email, customer_cpf, customer_phone
        )
        if status in (200, 201):
            asaas_customer_id = result.get('id')
        elif result.get('errors'):
            # Try to find existing customer
            for error in result.get('errors', []):
                if 'ja cadastrado' in str(error.get('description', '')).lower():
                    # Search by CPF
                    search_result, _ = asaas._request(
                        'GET', f'customers?cpfCnpj={customer_cpf}'
                    )
                    customers_list = search_result.get('data', [])
                    if customers_list:
                        asaas_customer_id = customers_list[0]['id']

    # Map payment method
    billing_type_map = {
        'PIX': 'PIX',
        'CREDIT_CARD': 'CREDIT_CARD',
        'DEBIT_CARD': 'CREDIT_CARD',  # Asaas uses CREDIT_CARD type for debit too
        'BOLETO': 'BOLETO'
    }
    billing_type = billing_type_map.get(payment_method, 'PIX')

    # Shipping calculation
    shipping_cep = request.form.get('shipping_cep', '').strip()
    shipping_method = request.form.get('shipping_method', '')
    shipping_cost = 0
    shipping_address = request.form.get('shipping_address', '')
    shipping_address_number = request.form.get('shipping_address_num', '')
    shipping_complement = request.form.get('shipping_complement', '')
    shipping_neighborhood = request.form.get('shipping_neighborhood', '')
    shipping_city = request.form.get('shipping_city', '')
    shipping_state = request.form.get('shipping_state', '')

    if shipping_cep and shipping_method:
        store_settings = get_item('settings', 'store') or {}
        options = shipping_service.calculate_shipping(shipping_cep, settings=store_settings)
        chosen = next((o for o in options if o['code'] == shipping_method), None)
        # Check free shipping threshold
        free_shipping_min = store_settings.get('free_shipping_min', 0)
        if free_shipping_min and total >= free_shipping_min:
            shipping_cost = 0
        elif chosen:
            shipping_cost = chosen['price']

    order_total = total + shipping_cost

    # Progressive discount
    store_settings = get_item('settings', 'store') or {}
    discount_amount = 0
    discount_label = ''
    progressive_discounts = store_settings.get('progressive_discounts', [])
    for tier in sorted(progressive_discounts, key=lambda t: t.get('min_value', 0), reverse=True):
        if total >= tier.get('min_value', 0):
            pct = tier.get('discount_percent', 0)
            discount_amount = round(total * pct / 100, 2)
            discount_label = f'{pct}% (acima de R$ {tier["min_value"]:.2f})'
            break

    order_total = order_total - discount_amount

    # Create order
    order_number = generate_order_number()
    order = {
        'id': str(uuid.uuid4()),
        'order_number': order_number,
        'customer_id': guest_customer_id,
        'customer_name': customer_name,
        'customer_email': customer_email,
        'customer_cpf': customer_cpf,
        'customer_phone': customer_phone,
        'items': order_items,
        'subtotal': total,
        'shipping_cost': shipping_cost,
        'shipping_method': shipping_method,
        'shipping_cep': shipping_cep,
        'shipping_address': shipping_address,
        'shipping_address_number': shipping_address_number,
        'shipping_complement': shipping_complement,
        'shipping_neighborhood': shipping_neighborhood,
        'shipping_city': shipping_city,
        'shipping_state': shipping_state,
        'discount_amount': discount_amount,
        'discount_label': discount_label,
        'total': order_total,
        'payment_method': payment_method,
        'payment_status': 'PENDING',
        'asaas_customer_id': asaas_customer_id,
        'asaas_payment_id': None,
        'status': 'awaiting_payment',
        'tracking_code': '',
        'tracking_url': '',
        'status_history': [
            {'status': 'awaiting_payment', 'date': datetime.now().isoformat(), 'note': 'Pedido criado'}
        ],
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }

    # Create Asaas payment
    if asaas_customer_id:
        installments = int(request.form.get('installments', 1))
        pay_result, pay_status = asaas.create_payment(
            asaas_customer_id, order_total, billing_type,
            f"Pedido {order_number} - Val's",
            installment_count=installments if billing_type == 'CREDIT_CARD' else None
        )

        if pay_status in (200, 201):
            order['asaas_payment_id'] = pay_result.get('id')
            order['payment_status'] = pay_result.get('status', 'PENDING')

            # Handle credit card immediate payment
            if billing_type == 'CREDIT_CARD':
                card_data = {
                    'holderName': request.form.get('card_holder_name', ''),
                    'number': request.form.get('card_number', '').replace(' ', ''),
                    'expiryMonth': request.form.get('card_expiry_month', ''),
                    'expiryYear': request.form.get('card_expiry_year', ''),
                    'ccv': request.form.get('card_cvv', '')
                }
                holder_info = {
                    'name': customer_name,
                    'email': customer_email,
                    'cpfCnpj': customer_cpf,
                    'phone': customer_phone,
                    'postalCode': request.form.get('postal_code', ''),
                    'addressNumber': request.form.get('address_number', '')
                }
                cc_result, cc_status = asaas.pay_with_credit_card(
                    pay_result['id'], card_data, holder_info
                )
                if cc_status in (200, 201):
                    order['payment_status'] = cc_result.get('status', 'CONFIRMED')
        else:
            order['payment_error'] = pay_result.get('errors', [])

    # Save order
    save_item('orders', order['id'], order)

    # Send order confirmation email
    if customer_email:
        email_service.send_order_confirmation_email(app, order)

    # Clear cart
    session['cart'] = []

    return redirect(url_for('order_confirmation', order_id=order['id']))


@app.route('/pedido/<order_id>')
def order_confirmation(order_id):
    """Order confirmation page with payment details."""
    data = load_data()
    order = next((o for o in data.get('orders', []) if o['id'] == order_id), None)

    if not order:
        flash('Pedido nao encontrado.', 'error')
        return redirect(url_for('index'))

    # Get PIX QR Code if applicable
    pix_data = None
    boleto_data = None

    if order.get('asaas_payment_id'):
        if order['payment_method'] == 'PIX':
            result, status = asaas.get_pix_qrcode(order['asaas_payment_id'])
            if status == 200:
                pix_data = result
        elif order['payment_method'] == 'BOLETO':
            result, status = asaas.get_boleto_url(order['asaas_payment_id'])
            if status == 200:
                boleto_data = result

    return render_template('order_confirmation.html',
                           order=order,
                           pix_data=pix_data,
                           boleto_data=boleto_data)


@app.route('/finalizar-pedido')
def checkout_whatsapp():
    """Legacy WhatsApp checkout."""
    cart_items = session.get('cart', [])
    if not cart_items:
        flash('Seu carrinho esta vazio!', 'error')
        return redirect(url_for('cart'))

    data = load_data()

    message = "*NOVO PEDIDO - VAL'S*\n"
    message += "=" * 35 + "\n\n"

    total = 0
    item_count = 1

    for item in cart_items:
        product = next((p for p in data['products'] if p['id'] == item['product_id']), None)
        if product:
            current_price = get_product_current_price(product)
            item_total = current_price * item['quantity']
            total += item_total

            message += f"*Item {item_count}:* {product['name']}\n"
            message += f"   Qtd: {item['quantity']} | Unit: R$ {current_price:.2f}\n"
            if item.get('description'):
                message += f"   Obs: {item['description']}\n"
            message += f"   Subtotal: *R$ {item_total:.2f}*\n"
            message += "-" * 30 + "\n"
            item_count += 1

    message += f"\n*TOTAL: R$ {total:.2f}*\n"
    message += "=" * 35 + "\n\n"
    message += "Ola! Gostaria de finalizar este pedido!\n"

    whatsapp_url = (
        f"https://wa.me/{WHATSAPP_NUMBER.replace('+', '').replace(' ', '')}"
        f"?text={urllib.parse.quote(message)}"
    )

    session['cart'] = []
    return redirect(whatsapp_url)


# ================================
# ASAAS WEBHOOK
# ================================
@app.route('/api/webhook/asaas', methods=['POST'])
def asaas_webhook():
    """Handle Asaas payment status updates."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'error': 'Invalid payload'}), 400

    event = payload.get('event')
    payment = payload.get('payment', {})
    payment_id = payment.get('id')

    if not payment_id:
        return jsonify({'ok': True}), 200

    data = load_data()
    order = next(
        (o for o in data.get('orders', []) if o.get('asaas_payment_id') == payment_id),
        None
    )

    if order:
        status_map = {
            'PAYMENT_CONFIRMED': 'CONFIRMED',
            'PAYMENT_RECEIVED': 'RECEIVED',
            'PAYMENT_OVERDUE': 'OVERDUE',
            'PAYMENT_REFUNDED': 'REFUNDED',
            'PAYMENT_DELETED': 'DELETED',
        }
        new_status = status_map.get(event, order['payment_status'])
        order['payment_status'] = new_status
        order['updated_at'] = datetime.now().isoformat()

        old_order_status = order.get('status')
        if new_status in ('CONFIRMED', 'RECEIVED'):
            order['status'] = 'paid'
        elif new_status == 'OVERDUE':
            order['status'] = 'overdue'
        elif new_status in ('REFUNDED', 'DELETED'):
            order['status'] = 'cancelled'

        # Add to status history if order status changed
        if order['status'] != old_order_status:
            history = order.get('status_history', [])
            history.append({
                'status': order['status'],
                'date': datetime.now().isoformat(),
                'note': _status_label(order['status'])
            })
            order['status_history'] = history

        save_item('orders', order['id'], order)

        # Send payment status email
        if order.get('customer_email'):
            email_service.send_payment_status_email(app, order)

    return jsonify({'ok': True}), 200


# ================================
# CUSTOMER AREA
# ================================
@app.route('/cadastro', methods=['GET', 'POST'])
def customer_register():
    if request.method == 'GET':
        captcha_question = generate_captcha()
        return render_template('customer/register.html', captcha_question=captcha_question)

    if not check_rate_limit(f"register_{request.remote_addr}", 5, 300):
        flash('Muitas tentativas de cadastro. Aguarde 5 minutos.', 'error')
        return redirect(url_for('customer_register'))

    # Verify captcha
    if not verify_captcha(request.form.get('captcha')):
        flash('Resposta do captcha incorreta.', 'error')
        return redirect(url_for('customer_register'))

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    cpf = request.form.get('cpf', '').strip()
    phone = request.form.get('phone', '').strip()

    # Validation
    if not all([name, email, password]):
        flash('Preencha todos os campos obrigatorios.', 'error')
        return redirect(url_for('customer_register'))

    if len(password) < 8:
        flash('A senha deve ter pelo menos 8 caracteres.', 'error')
        return redirect(url_for('customer_register'))

    if password != confirm_password:
        flash('As senhas nao conferem.', 'error')
        return redirect(url_for('customer_register'))

    data = load_data()
    cpf_clean = re.sub(r'[^\d]', '', cpf)

    # Check if there's a guest account with same CPF or email (from a previous purchase)
    guest = None
    for c in data['customers']:
        if c.get('is_guest'):
            c_cpf = re.sub(r'[^\d]', '', c.get('cpf', ''))
            if (c_cpf and c_cpf == cpf_clean) or (c.get('email') == email):
                guest = c
                break

    # Check duplicate email (only among non-guest accounts)
    registered = next(
        (c for c in data['customers']
         if c['email'] == email and not c.get('is_guest') and c.get('password')),
        None
    )
    if registered:
        flash('Este email ja esta cadastrado. Faca login.', 'error')
        return redirect(url_for('customer_login'))

    if guest:
        # Upgrade guest to full account — keeps same ID so orders stay linked
        guest['name'] = name
        guest['email'] = email
        guest['password'] = hash_password(password)
        guest['cpf'] = cpf_clean
        guest['phone'] = phone or guest.get('phone', '')
        guest['totp_secret'] = pyotp.random_base32()
        guest['totp_enabled'] = False
        guest['is_guest'] = False
        guest['registered_at'] = datetime.now().isoformat()
        customer = guest
        save_item('customers', customer['id'], customer)
    else:
        # Create brand new customer
        customer = {
            'id': str(uuid.uuid4()),
            'name': name,
            'email': email,
            'password': hash_password(password),
            'cpf': cpf_clean,
            'phone': phone,
            'totp_secret': pyotp.random_base32(),
            'totp_enabled': False,
            'created_at': datetime.now().isoformat()
        }
        save_item('customers', customer['id'], customer)

    # Send welcome email
    email_service.send_welcome_email(app, name, email)

    session['customer_id'] = customer['id']
    flash('Cadastro realizado com sucesso! Configure a autenticacao de 2 fatores para maior seguranca.', 'success')
    return redirect(url_for('customer_profile'))


@app.route('/login', methods=['GET', 'POST'])
def customer_login():
    if request.method == 'GET':
        captcha_question = generate_captcha()
        return render_template('customer/login.html', captcha_question=captcha_question)

    if not check_rate_limit(f"login_{request.remote_addr}", 5, 300):
        flash('Muitas tentativas de login. Aguarde 5 minutos.', 'error')
        return redirect(url_for('customer_login'))

    if not verify_captcha(request.form.get('captcha')):
        flash('Resposta do captcha incorreta.', 'error')
        return redirect(url_for('customer_login'))

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    data = load_data()
    customer = next((c for c in data['customers'] if c['email'] == email), None)

    if not customer or not verify_password(password, customer['password']):
        flash('Email ou senha incorretos.', 'error')
        return redirect(url_for('customer_login'))

    # Check 2FA
    if customer.get('totp_enabled'):
        session['pending_2fa_customer'] = customer['id']
        return redirect(url_for('customer_2fa_verify'))

    session['customer_id'] = customer['id']
    session.permanent = True
    flash(f'Bem-vinda, {customer["name"]}!', 'success')

    next_url = request.args.get('next', url_for('customer_profile'))
    return redirect(next_url)


# --- Password Recovery ---
_password_reset_tokens = {}  # {token: {'customer_id': ..., 'expires': datetime}}

@app.route('/esqueci-senha', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        captcha_question = generate_captcha()
        return render_template('customer/forgot_password.html', captcha_question=captcha_question)

    if not check_rate_limit(f"forgot_{request.remote_addr}", 3, 300):
        flash('Muitas tentativas. Aguarde 5 minutos.', 'error')
        return redirect(url_for('forgot_password'))

    if not verify_captcha(request.form.get('captcha')):
        flash('Resposta do captcha incorreta.', 'error')
        return redirect(url_for('forgot_password'))

    email = request.form.get('email', '').strip().lower()
    data = load_data()
    customer = next((c for c in data['customers'] if c['email'] == email), None)

    # Always show success message (prevent email enumeration)
    if customer:
        token = email_service.generate_password_reset_token()
        _password_reset_tokens[token] = {
            'customer_id': customer['id'],
            'expires': datetime.now() + timedelta(hours=1)
        }
        reset_url = url_for('reset_password', token=token, _external=True)
        email_service.send_password_reset_email(app, email, customer['name'], reset_url)

    flash('Se o email estiver cadastrado, voce recebera um link para redefinir sua senha.', 'info')
    return redirect(url_for('customer_login'))


@app.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_data = _password_reset_tokens.get(token)
    if not token_data or datetime.now() > token_data['expires']:
        flash('Link expirado ou invalido. Solicite um novo.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'GET':
        return render_template('customer/reset_password.html', token=token)

    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    if len(password) < 8:
        flash('A senha deve ter pelo menos 8 caracteres.', 'error')
        return redirect(url_for('reset_password', token=token))

    if password != confirm_password:
        flash('As senhas nao conferem.', 'error')
        return redirect(url_for('reset_password', token=token))

    customer = get_customer(token_data['customer_id'])
    if customer:
        customer['password'] = hash_password(password)
        save_item('customers', customer['id'], customer)
        del _password_reset_tokens[token]
        flash('Senha redefinida com sucesso! Faca login.', 'success')
    else:
        flash('Erro ao redefinir senha.', 'error')

    return redirect(url_for('customer_login'))


@app.route('/2fa/verificar', methods=['GET', 'POST'])
def customer_2fa_verify():
    if not session.get('pending_2fa_customer'):
        return redirect(url_for('customer_login'))

    if request.method == 'GET':
        return render_template('customer/2fa_verify.html')

    token = request.form.get('token', '').strip()
    customer_id = session.get('pending_2fa_customer')
    customer = get_customer(customer_id)

    if not customer:
        return redirect(url_for('customer_login'))

    totp = pyotp.TOTP(customer['totp_secret'])
    if totp.verify(token, valid_window=1):
        session.pop('pending_2fa_customer', None)
        session['customer_id'] = customer['id']
        session.permanent = True
        flash(f'Bem-vinda, {customer["name"]}!', 'success')
        return redirect(url_for('customer_profile'))
    else:
        flash('Codigo invalido. Tente novamente.', 'error')
        return redirect(url_for('customer_2fa_verify'))


@app.route('/logout')
def customer_logout():
    session.pop('customer_id', None)
    flash('Voce saiu da sua conta.', 'info')
    return redirect(url_for('index'))


@app.route('/minha-conta')
@login_required
def customer_profile():
    customer = get_customer(session['customer_id'])
    data = load_data()
    orders = [
        o for o in data.get('orders', [])
        if o.get('customer_id') == session['customer_id']
    ]
    orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template('customer/profile.html', customer=customer, orders=orders)


@app.route('/minha-conta/editar', methods=['POST'])
@login_required
def customer_profile_update():
    data = load_data()
    customer = next(
        (c for c in data['customers'] if c['id'] == session['customer_id']), None
    )
    if not customer:
        return redirect(url_for('customer_login'))

    customer['name'] = request.form.get('name', customer['name']).strip()
    customer['phone'] = request.form.get('phone', customer['phone']).strip()
    customer['cpf'] = request.form.get('cpf', customer['cpf']).strip()

    # Password change
    new_password = request.form.get('new_password', '')
    if new_password:
        if len(new_password) < 8:
            flash('A nova senha deve ter pelo menos 8 caracteres.', 'error')
            return redirect(url_for('customer_profile'))
        customer['password'] = hash_password(new_password)

    save_item('customers', customer['id'], customer)
    flash('Perfil atualizado com sucesso!', 'success')
    return redirect(url_for('customer_profile'))


@app.route('/minha-conta/2fa/configurar', methods=['GET', 'POST'])
@login_required
def customer_2fa_setup():
    customer = get_customer(session['customer_id'])

    if request.method == 'GET':
        totp = pyotp.TOTP(customer['totp_secret'])
        provisioning_uri = totp.provisioning_uri(
            name=customer['email'],
            issuer_name="Val's Luxury"
        )
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color='#1B2A4A', back_color='#FAF8F5')
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()

        return render_template('customer/2fa_setup.html',
                               customer=customer,
                               qr_code=qr_base64,
                               secret=customer['totp_secret'])

    # Verify setup
    token = request.form.get('token', '').strip()
    totp = pyotp.TOTP(customer['totp_secret'])

    if totp.verify(token, valid_window=1):
        customer['totp_enabled'] = True
        save_item('customers', customer['id'], customer)
        flash('Autenticacao de 2 fatores ativada com sucesso!', 'success')
        return redirect(url_for('customer_profile'))
    else:
        flash('Codigo invalido. Tente novamente.', 'error')
        return redirect(url_for('customer_2fa_setup'))


@app.route('/minha-conta/pedidos')
@login_required
def customer_orders():
    data = load_data()
    orders = [
        o for o in data.get('orders', [])
        if o.get('customer_id') == session['customer_id']
    ]
    orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template('customer/orders.html', orders=orders)


@app.route('/minha-conta/pedido/<order_id>')
@login_required
def customer_order_detail(order_id):
    data = load_data()
    order = next(
        (o for o in data.get('orders', [])
         if o['id'] == order_id and o.get('customer_id') == session['customer_id']),
        None
    )
    if not order:
        flash('Pedido nao encontrado.', 'error')
        return redirect(url_for('customer_orders'))

    return render_template('customer/order_detail.html', order=order)


# ================================
# ADMIN AREA
# ================================
@app.route('/admin')
def admin_login():
    return render_template('admin/login.html')

@app.route('/admin/login', methods=['POST'])
def admin_authenticate():
    if not check_rate_limit(f"admin_login_{request.remote_addr}", 3, 300):
        flash('Muitas tentativas. Aguarde 5 minutos.', 'error')
        return redirect(url_for('admin_login'))

    password = request.form.get('password')
    data = load_data()

    if password == data.get('admin_password', 'primaarte2025'):
        session['admin'] = True
        return redirect(url_for('admin_dashboard'))
    else:
        flash('Senha incorreta!', 'error')
        return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    data = load_data()
    orders = data.get('orders', [])

    # Revenue calculations
    total_revenue = sum(
        o['total'] for o in orders
        if o.get('payment_status') in ('CONFIRMED', 'RECEIVED')
    )
    pending_orders = [o for o in orders if o.get('status') == 'pending']
    paid_orders = [o for o in orders if o.get('status') == 'paid']

    stats = {
        'total_products': len(data['products']),
        'total_announcements': len(data['announcements']),
        'active_announcements': len([a for a in data['announcements'] if a.get('active', True)]),
        'total_orders': len(orders),
        'pending_orders': len(pending_orders),
        'paid_orders': len(paid_orders),
        'total_revenue': total_revenue,
        'total_customers': len(data.get('customers', []))
    }

    recent_orders = sorted(
        orders, key=lambda x: x.get('created_at', ''), reverse=True
    )[:10]

    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_orders=recent_orders)

@app.route('/admin/pedidos')
@admin_required
def admin_orders():
    data = load_data()
    status_filter = request.args.get('status', '')
    orders = data.get('orders', [])

    if status_filter:
        orders = [o for o in orders if o.get('status') == status_filter]

    orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template('admin/orders.html', orders=orders, current_status=status_filter)

@app.route('/admin/pedido/<order_id>')
@admin_required
def admin_order_detail(order_id):
    data = load_data()
    order = next((o for o in data.get('orders', []) if o['id'] == order_id), None)

    if not order:
        flash('Pedido nao encontrado.', 'error')
        return redirect(url_for('admin_orders'))

    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/pedido/<order_id>/status', methods=['POST'])
@admin_required
def admin_update_order_status(order_id):
    data = load_data()
    order = next((o for o in data.get('orders', []) if o['id'] == order_id), None)

    if order:
        new_status = request.form.get('status', order['status'])
        tracking_code = request.form.get('tracking_code', '').strip()
        status_note = request.form.get('status_note', '').strip()

        order['status'] = new_status
        order['updated_at'] = datetime.now().isoformat()

        if tracking_code:
            order['tracking_code'] = tracking_code
            order['tracking_url'] = f'https://www.linkcorreios.com.br/?id={tracking_code}'

        # Add to status history
        history = order.get('status_history', [])
        history.append({
            'status': new_status,
            'date': datetime.now().isoformat(),
            'note': status_note or _status_label(new_status)
        })
        order['status_history'] = history

        save_item('orders', order['id'], order)

        # Send order status email
        if order.get('customer_email'):
            email_service.send_order_status_email(app, order)

        flash('Status do pedido atualizado!', 'success')

    return redirect(url_for('admin_order_detail', order_id=order_id))


def _status_label(status):
    """Return human-readable label for order status."""
    labels = {
        'awaiting_payment': 'Aguardando Pagamento',
        'paid': 'Pagamento Confirmado',
        'invoicing': 'Emitindo Nota Fiscal',
        'packing': 'Embalando',
        'shipped': 'Enviado',
        'in_transit': 'Em Transito',
        'delivered': 'Entregue',
        'cancelled': 'Cancelado',
        'pending': 'Pendente',
    }
    return labels.get(status, status)


# ================================
# INVOICE GENERATION
# ================================
@app.route('/admin/pedido/<order_id>/nota-fiscal')
@admin_required
def admin_generate_invoice(order_id):
    """Generate a PDF invoice for an order."""
    data = load_data()
    order = next((o for o in data.get('orders', []) if o['id'] == order_id), None)

    if not order:
        flash('Pedido nao encontrado.', 'error')
        return redirect(url_for('admin_orders'))

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.pdfgen import canvas as pdf_canvas

        buffer = BytesIO()
        c = pdf_canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        # Colors
        navy = HexColor('#1B2A4A')
        gold = HexColor('#C9A84C')
        gray = HexColor('#8A8A8A')

        # Header
        c.setFillColor(navy)
        c.rect(0, height - 80, width, 80, fill=True)
        c.setFillColor(HexColor('#FAF8F5'))
        c.setFont('Helvetica-Bold', 24)
        c.drawString(30, height - 50, "VAL'S")
        c.setFont('Helvetica', 8)
        c.drawString(30, height - 65, "LUXURY HANDCRAFTED")

        c.setFont('Helvetica-Bold', 14)
        c.drawRightString(width - 30, height - 45, "NOTA FISCAL")
        c.setFont('Helvetica', 9)
        c.drawRightString(width - 30, height - 60, f"Pedido: {order.get('order_number', '')}")

        y = height - 110

        # Customer info
        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(30, y, "DADOS DO CLIENTE")
        y -= 5
        c.setStrokeColor(gold)
        c.setLineWidth(1)
        c.line(30, y, width - 30, y)
        y -= 18

        c.setFont('Helvetica', 9)
        c.setFillColor(HexColor('#333333'))
        c.drawString(30, y, f"Nome: {order.get('customer_name', 'N/A')}")
        y -= 15
        c.drawString(30, y, f"Email: {order.get('customer_email', 'N/A')}")
        c.drawString(300, y, f"CPF: {order.get('customer_cpf', 'N/A')}")
        y -= 15
        c.drawString(30, y, f"Telefone: {order.get('customer_phone', 'N/A')}")
        c.drawString(300, y, f"Data: {order.get('created_at', '')[:10]}")
        y -= 30

        # Items table header
        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(30, y, "ITENS DO PEDIDO")
        y -= 5
        c.setStrokeColor(gold)
        c.line(30, y, width - 30, y)
        y -= 20

        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(30, y, "PRODUTO")
        c.drawString(300, y, "QTD")
        c.drawString(370, y, "PRECO UNIT.")
        c.drawRightString(width - 30, y, "SUBTOTAL")
        y -= 5
        c.setStrokeColor(gray)
        c.setLineWidth(0.5)
        c.line(30, y, width - 30, y)
        y -= 15

        c.setFont('Helvetica', 9)
        c.setFillColor(HexColor('#333333'))
        for item in order.get('items', []):
            c.drawString(30, y, item.get('name', ''))
            c.drawString(310, y, str(item.get('quantity', 1)))
            c.drawString(370, y, f"R$ {item.get('price', 0):.2f}")
            c.drawRightString(width - 30, y, f"R$ {item.get('subtotal', 0):.2f}")
            y -= 18

        # Total
        y -= 10
        c.setStrokeColor(navy)
        c.setLineWidth(1)
        c.line(300, y, width - 30, y)
        y -= 20
        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 12)
        c.drawString(300, y, "TOTAL:")
        c.drawRightString(width - 30, y, f"R$ {order.get('total', 0):.2f}")

        y -= 15
        c.setFont('Helvetica', 8)
        c.setFillColor(gray)
        payment_labels = {
            'PIX': 'PIX', 'CREDIT_CARD': 'Cartao de Credito', 'BOLETO': 'Boleto'
        }
        c.drawString(300, y, f"Pagamento: {payment_labels.get(order.get('payment_method', ''), 'N/A')}")

        status_labels = {
            'pending': 'Pendente', 'paid': 'Pago',
            'shipped': 'Enviado', 'delivered': 'Entregue',
            'cancelled': 'Cancelado', 'overdue': 'Vencido'
        }
        y -= 15
        c.drawString(300, y, f"Status: {status_labels.get(order.get('status', ''), 'N/A')}")

        # Footer
        c.setFillColor(navy)
        c.rect(0, 0, width, 40, fill=True)
        c.setFillColor(HexColor('#FAF8F5'))
        c.setFont('Helvetica', 7)
        c.drawCentredString(width / 2, 20, "Val's - Luxury Handcrafted | Colecao Riviera Botanica")
        c.drawCentredString(width / 2, 10, f"Documento gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

        c.showPage()
        c.save()

        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = (
            f'attachment; filename=NF_{order.get("order_number", order_id)}.pdf'
        )
        return response

    except ImportError:
        flash('Biblioteca reportlab nao instalada. Execute: pip install reportlab', 'error')
        return redirect(url_for('admin_order_detail', order_id=order_id))


# ================================
# ADMIN - PRODUCTS (existing)
# ================================
@app.route('/admin/produtos')
@admin_required
def admin_products():
    data = load_data()
    return render_template('admin/products.html', products=data['products'])

@app.route('/admin/produto/novo')
@admin_required
def admin_product_new():
    return render_template('admin/product_form.html', product=None)

@app.route('/admin/produto/editar/<product_id>')
@admin_required
def admin_product_edit(product_id):
    data = load_data()
    product = next((p for p in data['products'] if p['id'] == product_id), None)
    if not product:
        flash('Produto nao encontrado!', 'error')
        return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/produto/salvar', methods=['POST'])
@admin_required
def admin_save_product():
    data = load_data()

    product_id = request.form.get('id') or str(uuid.uuid4())
    product_name = request.form.get('name')

    regular_price = float(request.form.get('price', 0))
    promotional_price = request.form.get('promotional_price')
    promotional_price = float(promotional_price) if promotional_price and promotional_price.strip() else None
    promotion_active = request.form.get('promotion_active') == 'on'

    uploaded_images = []
    if 'images' in request.files:
        files = request.files.getlist('images')
        for file in files:
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"{int(datetime.now().timestamp())}_{filename}"
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(file_path)
                uploaded_images.append(f"/static/uploads/{filename}")

    existing_product = next((p for p in data['products'] if p['id'] == product_id), None)
    if existing_product and not uploaded_images:
        uploaded_images = existing_product.get('images', [])

    product = {
        'id': product_id,
        'name': product_name,
        'description': request.form.get('description'),
        'price': regular_price,
        'promotional_price': promotional_price,
        'promotion_active': promotion_active,
        'category': request.form.get('category'),
        'images': uploaded_images,
        'featured': request.form.get('featured') == 'on',
        'is_unique': request.form.get('is_unique') == 'on',
        'stock_quantity': int(request.form.get('stock_quantity', 1)),
        'created_at': (
            existing_product.get('created_at', datetime.now().isoformat())
            if existing_product else datetime.now().isoformat()
        ),
        'updated_at': datetime.now().isoformat()
    }

    save_item('products', product['id'], product)

    if promotion_active and promotional_price:
        discount_percent = calculate_discount_percentage(regular_price, promotional_price)
        flash(f'Produto "{product_name}" salvo com {discount_percent}% de desconto!', 'success')
    else:
        flash(f'Produto "{product_name}" salvo com sucesso!', 'success')

    return redirect(url_for('admin_products'))

@app.route('/admin/produto/excluir/<product_id>')
@admin_required
def admin_product_delete(product_id):
    data = load_data()

    product = next((p for p in data['products'] if p['id'] == product_id), None)
    if product and product.get('images'):
        for image_url in product['images']:
            if image_url.startswith('/static/uploads/'):
                image_path = image_url[1:]
                if os.path.exists(image_path):
                    os.remove(image_path)

    delete_item('products', product_id)

    flash('Produto excluido com sucesso!', 'success')
    return redirect(url_for('admin_products'))


# ================================
# ADMIN - ANNOUNCEMENTS (existing)
# ================================
@app.route('/admin/anuncios')
@admin_required
def admin_announcements():
    data = load_data()
    return render_template('admin/announcements.html',
                           announcements=data.get('announcements', []))

@app.route('/admin/anuncio/novo')
@admin_required
def admin_new_announcement():
    return render_template('admin/announcement_form.html', announcement=None)

@app.route('/admin/anuncio/editar/<announcement_id>')
@admin_required
def admin_edit_announcement(announcement_id):
    data = load_data()
    announcement = next(
        (a for a in data['announcements'] if a['id'] == announcement_id), None
    )
    if not announcement:
        flash('Anuncio nao encontrado!', 'error')
        return redirect(url_for('admin_announcements'))
    return render_template('admin/announcement_form.html', announcement=announcement)

@app.route('/admin/anuncio/salvar', methods=['POST'])
@admin_required
def admin_save_announcement():
    data = load_data()

    announcement_id = request.form.get('id') or str(uuid.uuid4())
    announcement_title = request.form.get('title')

    uploaded_image = ''
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"{int(datetime.now().timestamp())}_{filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            uploaded_image = f"/static/uploads/{filename}"

    existing_announcement = next(
        (a for a in data['announcements'] if a['id'] == announcement_id), None
    )
    if existing_announcement and not uploaded_image:
        uploaded_image = existing_announcement.get('image', '')

    announcement = {
        'id': announcement_id,
        'title': announcement_title,
        'content': request.form.get('content'),
        'image': uploaded_image,
        'active': request.form.get('active') == 'on',
        'created_at': (
            existing_announcement.get('created_at', datetime.now().isoformat())
            if existing_announcement else datetime.now().isoformat()
        ),
        'updated_at': datetime.now().isoformat()
    }

    save_item('announcements', announcement['id'], announcement)
    flash(f'Anuncio "{announcement_title}" salvo com sucesso!', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/anuncio/excluir/<announcement_id>')
@admin_required
def admin_delete_announcement(announcement_id):
    data = load_data()

    announcement = next(
        (a for a in data['announcements'] if a['id'] == announcement_id), None
    )
    if announcement and announcement.get('image'):
        if announcement['image'].startswith('/static/uploads/'):
            image_path = announcement['image'][1:]
            if os.path.exists(image_path):
                os.remove(image_path)

    delete_item('announcements', announcement_id)

    flash('Anuncio excluido com sucesso!', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/clientes')
@admin_required
def admin_customers():
    data = load_data()
    return render_template('admin/customers.html', customers=data.get('customers', []))

@app.route('/admin/configuracoes', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    settings = get_item('settings', 'store') or {}

    if request.method == 'POST':
        settings['default_weight'] = float(request.form.get('default_weight', 0.5))
        settings['default_length'] = float(request.form.get('default_length', 30))
        settings['default_width'] = float(request.form.get('default_width', 25))
        settings['default_height'] = float(request.form.get('default_height', 15))
        settings['origin_cep'] = request.form.get('origin_cep', '28900000').strip()
        settings['free_shipping_min'] = float(request.form.get('free_shipping_min', 0))

        # Progressive discounts
        disc_mins = request.form.getlist('disc_min_value')
        disc_pcts = request.form.getlist('disc_percent')
        progressive = []
        for mv, pct in zip(disc_mins, disc_pcts):
            try:
                mv_f = float(mv)
                pct_f = float(pct)
                if mv_f > 0 and pct_f > 0:
                    progressive.append({'min_value': mv_f, 'discount_percent': pct_f})
            except (ValueError, TypeError):
                continue
        settings['progressive_discounts'] = sorted(progressive, key=lambda x: x['min_value'])

        settings['id'] = 'store'
        save_item('settings', 'store', settings)
        flash('Configuracoes salvas!', 'success')
        return redirect(url_for('admin_settings'))

    return render_template('admin/settings.html', settings=settings)


@app.route('/admin/vendas')
@admin_required
def admin_sales():
    data = load_data()
    orders = data.get('orders', [])

    # Overall stats
    all_paid = [o for o in orders if o.get('payment_status') in ('CONFIRMED', 'RECEIVED')]
    total_revenue = sum(o.get('total', 0) for o in all_paid)
    total_orders = len(orders)
    total_paid = len(all_paid)
    avg_ticket = total_revenue / total_paid if total_paid else 0

    # Monthly breakdown (last 6 months)
    from collections import defaultdict
    monthly = defaultdict(lambda: {'revenue': 0, 'count': 0})
    for o in all_paid:
        month_key = o.get('created_at', '')[:7]  # YYYY-MM
        if month_key:
            monthly[month_key]['revenue'] += o.get('total', 0)
            monthly[month_key]['count'] += 1
    monthly_sorted = sorted(monthly.items(), reverse=True)[:6]

    # Payment method breakdown
    method_stats = defaultdict(lambda: {'count': 0, 'revenue': 0})
    for o in all_paid:
        m = o.get('payment_method', 'N/A')
        method_stats[m]['count'] += 1
        method_stats[m]['revenue'] += o.get('total', 0)

    # Top products
    product_stats = defaultdict(lambda: {'qty': 0, 'revenue': 0})
    for o in all_paid:
        for item in o.get('items', []):
            product_stats[item['name']]['qty'] += item.get('quantity', 1)
            product_stats[item['name']]['revenue'] += item.get('subtotal', 0)
    top_products = sorted(product_stats.items(), key=lambda x: x[1]['revenue'], reverse=True)[:10]

    # Status breakdown
    status_counts = defaultdict(int)
    for o in orders:
        status_counts[o.get('status', 'unknown')] += 1

    return render_template('admin/sales.html',
                           total_revenue=total_revenue,
                           total_orders=total_orders,
                           total_paid=total_paid,
                           avg_ticket=avg_ticket,
                           monthly=monthly_sorted,
                           method_stats=dict(method_stats),
                           top_products=top_products,
                           status_counts=dict(status_counts))


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('index'))


# ================================
# API ENDPOINTS
# ================================
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nenhum arquivo selecionado'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filename = f"{int(datetime.now().timestamp())}_{filename}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        return jsonify({'url': f"/static/uploads/{filename}"})

    return jsonify({'error': 'Tipo de arquivo nao permitido'}), 400

@app.route('/api/payment-status/<order_id>')
def api_payment_status(order_id):
    """Check payment status for polling."""
    data = load_data()
    order = next((o for o in data.get('orders', []) if o['id'] == order_id), None)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    # Optionally refresh from Asaas
    if order.get('asaas_payment_id') and order.get('payment_status') == 'PENDING':
        result, status = asaas.get_payment(order['asaas_payment_id'])
        if status == 200:
            new_status = result.get('status')
            if new_status != order.get('payment_status'):
                order['payment_status'] = new_status
                if new_status in ('CONFIRMED', 'RECEIVED'):
                    order['status'] = 'paid'
                order['updated_at'] = datetime.now().isoformat()
                save_item('orders', order['id'], order)

    return jsonify({
        'status': order.get('status'),
        'payment_status': order.get('payment_status')
    })


@app.route('/api/shipping/calculate', methods=['POST'])
def api_calculate_shipping():
    """Calculate shipping cost by CEP."""
    cep = request.json.get('cep', '') if request.is_json else request.form.get('cep', '')
    if not cep:
        return jsonify({'error': 'CEP obrigatorio'}), 400

    address = shipping_service.get_address_by_cep(cep)
    if not address:
        return jsonify({'error': 'CEP invalido'}), 400

    store_settings = get_item('settings', 'store') or {}
    options = shipping_service.calculate_shipping(cep, settings=store_settings)

    # Check free shipping
    cart_total = 0
    cart_items = session.get('cart', [])
    data = load_data()
    for item in cart_items:
        product = next((p for p in data['products'] if p['id'] == item['product_id']), None)
        if product:
            cart_total += get_product_current_price(product) * item['quantity']

    free_shipping_min = store_settings.get('free_shipping_min', 0)
    free_shipping = free_shipping_min > 0 and cart_total >= free_shipping_min

    # Also compute progressive discount
    discount_info = None
    progressive_discounts = store_settings.get('progressive_discounts', [])
    for tier in sorted(progressive_discounts, key=lambda t: t.get('min_value', 0), reverse=True):
        if cart_total >= tier.get('min_value', 0):
            discount_info = {
                'percent': tier['discount_percent'],
                'amount': round(cart_total * tier['discount_percent'] / 100, 2),
                'label': f'{tier["discount_percent"]}% de desconto'
            }
            break

    return jsonify({
        'address': address,
        'options': options,
        'free_shipping': free_shipping,
        'free_shipping_min': free_shipping_min,
        'discount': discount_info
    })


# ================================
# ERROR HANDLERS
# ================================
@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
