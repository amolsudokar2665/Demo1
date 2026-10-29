import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, redirect, url_for, render_template, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///nakkasi.db').replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['UPI_ID'] = os.getenv('UPI_ID', 'YOUR-UPI-ID@BANK')
app.config['STORE_NAME'] = 'Nakkasi – The Studio'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ORDER_STATUSES = {'Pending payment', 'Payment submitted', 'Paid', 'Processing', 'Shipped', 'Delivered', 'Cancelled'}

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default='')
    category = db.Column(db.String(80), nullable=False, default='Earrings')
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_url = db.Column(db.String(500), default='')
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def as_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description, 'category': self.category,
                'price': float(self.price), 'stock': self.stock, 'image_url': self.image_url, 'active': self.active}

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(24), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    phone = db.Column(db.String(25), nullable=False)
    address = db.Column(db.Text, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(40), default='Pending payment', nullable=False)
    payment_method = db.Column(db.String(30), default='Manual UPI', nullable=False)
    upi_reference = db.Column(db.String(100), default='')
    admin_note = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan', lazy=True)

    def as_dict(self, include_private=True):
        result = {'order_number': self.order_number, 'customer_name': self.customer_name,
                  'total_amount': float(self.total_amount), 'status': self.status,
                  'payment_method': self.payment_method, 'created_at': self.created_at.isoformat(),
                  'items': [{'product_id': i.product_id, 'product_name': i.product_name,
                             'quantity': i.quantity, 'unit_price': float(i.unit_price),
                             'line_total': float(i.unit_price * i.quantity)} for i in self.items]}
        if include_private:
            result.update({'email': self.email, 'phone': self.phone, 'address': self.address,
                           'upi_reference': self.upi_reference, 'admin_note': self.admin_note})
        return result

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    product_name = db.Column(db.String(160), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)

class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_id'):
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def json_error(message, status=400):
    return jsonify({'error': message}), status

@app.get('/')
def home():
    return jsonify({'store': app.config['STORE_NAME'], 'message': 'Nakkasi backend is running', 'api': '/api/products'})

@app.get('/health')
def health():
    return jsonify({'status': 'ok'})

@app.get('/api/products')
def list_products():
    products = Product.query.filter_by(active=True).order_by(Product.created_at.desc()).all()
    return jsonify({'products': [p.as_dict() for p in products]})

@app.get('/api/products/<int:product_id>')
def get_product(product_id):
    p = Product.query.filter_by(id=product_id, active=True).first_or_404()
    return jsonify(p.as_dict())

@app.post('/api/orders')
def create_order():
    data = request.get_json(silent=True) or {}
    required = ['customer_name', 'email', 'phone', 'address', 'items']
    if any(not data.get(k) for k in required):
        return json_error('Required fields: customer_name, email, phone, address, items.')
    if not isinstance(data['items'], list) or not data['items'] or len(data['items']) > 50:
        return json_error('items must be a non-empty list of up to 50 items.')
    if '@' not in str(data['email']) or len(str(data['email'])) > 254:
        return json_error('Please provide a valid email address.')
    if len(str(data['customer_name'])) > 120 or len(str(data['phone'])) > 25 or len(str(data['address'])) > 2000:
        return json_error('One or more customer fields are too long.')

    # Prices are always read from the database; client-submitted prices are ignored.
    order_lines, total = [], Decimal('0.00')
    for raw in data['items']:
        try:
            product_id = int(raw.get('product_id'))
            qty = int(raw.get('quantity'))
        except (TypeError, ValueError, AttributeError):
            return json_error('Each item requires a valid product_id and integer quantity.')
        if qty < 1 or qty > 25:
            return json_error('Quantity must be between 1 and 25 per product.')
        product = Product.query.filter_by(id=product_id, active=True).with_for_update().first()
        if not product:
            return json_error(f'Product {product_id} is unavailable.', 404)
        if product.stock < qty:
            return json_error(f'Not enough stock for {product.name}. Available: {product.stock}.', 409)
        line_total = Decimal(str(product.price)) * qty
        total += line_total
        order_lines.append((product, qty))

    order_number = 'NK' + datetime.now().strftime('%y%m%d') + secrets.token_hex(3).upper()
    order = Order(order_number=order_number, customer_name=str(data['customer_name']).strip(),
                  email=str(data['email']).strip(), phone=str(data['phone']).strip(),
                  address=str(data['address']).strip(), total_amount=total,
                  status='Pending payment', payment_method='Manual UPI')
    db.session.add(order)
    db.session.flush()
    for product, qty in order_lines:
        db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                                 quantity=qty, unit_price=product.price))
        product.stock -= qty
    db.session.commit()
    return jsonify({'message': 'Order created. Complete UPI payment and submit the UTR/reference number.',
                    'order': order.as_dict(), 'upi_id': app.config['UPI_ID'],
                    'payee_name': app.config['STORE_NAME']}), 201

@app.post('/api/orders/<order_number>/payment-reference')
def submit_payment_reference(order_number):
    data = request.get_json(silent=True) or {}
    reference = str(data.get('upi_reference', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    if not reference or len(reference) > 100:
        return json_error('Enter the UPI transaction reference/UTR (up to 100 characters).')
    order = Order.query.filter_by(order_number=order_number, email=email).first()
    if not order:
        return json_error('Order not found for that order number and email.', 404)
    if order.status not in {'Pending payment', 'Payment submitted'}:
        return json_error('Payment reference cannot be changed for this order.', 409)
    order.upi_reference = reference
    order.status = 'Payment submitted'
    db.session.commit()
    return jsonify({'message': 'Reference submitted. The store will verify the payment manually.',
                    'order_number': order.order_number, 'status': order.status})

@app.get('/api/orders/<order_number>')
def order_status(order_number):
    email = request.args.get('email', '').strip().lower()
    order = Order.query.filter_by(order_number=order_number, email=email).first()
    if not order:
        return json_error('Order not found for that order number and email.', 404)
    return jsonify(order.as_dict(include_private=False))

@app.get('/admin/login')
def admin_login():
    return render_template('login.html')

@app.post('/admin/login')
def admin_login_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    user = AdminUser.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        flash('Invalid username or password.', 'error')
        return render_template('login.html'), 401
    session.clear()
    session['admin_id'] = user.id
    session['admin_username'] = user.username
    return redirect(url_for('admin_dashboard'))

@app.post('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.get('/admin')
@admin_required
def admin_dashboard():
    orders = Order.query.order_by(Order.created_at.desc()).limit(100).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('dashboard.html', orders=orders, products=products, upi_id=app.config['UPI_ID'])

@app.post('/admin/products')
@admin_required
def admin_create_product():
    try:
        name = request.form.get('name', '').strip()
        category = request.form.get('category', 'Earrings').strip()
        description = request.form.get('description', '').strip()
        price = Decimal(request.form.get('price', '0'))
        stock = int(request.form.get('stock', '0'))
    except (InvalidOperation, ValueError):
        flash('Enter a valid price and stock quantity.', 'error')
        return redirect(url_for('admin_dashboard'))
    if not name or len(name) > 160 or price < 0 or stock < 0 or stock > 100000:
        flash('Please check the product details.', 'error')
        return redirect(url_for('admin_dashboard'))
    image_url = ''
    file = request.files.get('image')
    if file and file.filename:
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            flash('Image must be PNG, JPG, JPEG, or WEBP.', 'error')
            return redirect(url_for('admin_dashboard'))
        safe_name = secrets.token_hex(8) + '.' + ext
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], safe_name))
        image_url = '/static/uploads/' + safe_name
    product = Product(name=name, category=category[:80], description=description[:2000], price=price, stock=stock, image_url=image_url)
    db.session.add(product)
    db.session.commit()
    flash('Product added.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.post('/admin/products/<int:product_id>/update')
@admin_required
def admin_update_product(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        product.price = Decimal(request.form.get('price', str(product.price)))
        product.stock = int(request.form.get('stock', str(product.stock)))
    except (InvalidOperation, ValueError):
        flash('Invalid price or stock.', 'error')
        return redirect(url_for('admin_dashboard'))
    if product.price < 0 or product.stock < 0:
        flash('Price and stock cannot be negative.', 'error')
        return redirect(url_for('admin_dashboard'))
    product.active = request.form.get('active') == 'on'
    db.session.commit()
    flash('Product updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.post('/admin/orders/<order_number>/update')
@admin_required
def admin_update_order(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    status = request.form.get('status', '')
    if status not in ORDER_STATUSES:
        abort(400)
    # Mark Paid only after checking the transaction in the bank/UPI app.
    order.status = status
    order.admin_note = request.form.get('admin_note', '')[:500]
    db.session.commit()
    flash(f'Order {order.order_number} updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.cli.command('init-db')
def init_db():
    """Create tables and an initial admin if environment variables are set."""
    db.create_all()
    username = os.getenv('ADMIN_USERNAME')
    password = os.getenv('ADMIN_PASSWORD')
    if username and password:
        existing = AdminUser.query.filter_by(username=username).first()
        if not existing:
            db.session.add(AdminUser(username=username, password_hash=generate_password_hash(password)))
            db.session.commit()
            print(f'Created admin user: {username}')
        else:
            print('Admin user already exists; no changes made.')
    print('Database initialized.')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False)
