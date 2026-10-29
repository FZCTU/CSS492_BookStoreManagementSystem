import os
import sys
import sqlite3
import webbrowser
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "bookstore-capstone-secret-cs492-2026"

# Database file in current directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
DB_NAME = os.path.join(BASE_DIR, "bookstore.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_NAME)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def log_audit(action, entity, entity_id=None, details=None):
    """Audit logging helper for EP-10 Data Protection & Auditing."""
    try:
        db = get_db()
        user_id = session.get("user_id")
        user_email = session.get("email", "System/Anonymous")
        db.execute("""
            INSERT INTO audit_logs (user_id, user_email, action, entity, entity_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, user_email, action, entity, str(entity_id) if entity_id else None, details))
        db.commit()
    except Exception as e:
        print(f"Audit log failed: {e}", flush=True)

def init_db():
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    # 1. Users table (EP-01)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer', 'employee', 'admin')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Books table (EP-02, EP-03)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identifier TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        edition TEXT,
        category TEXT NOT NULL,
        condition TEXT NOT NULL,
        price REAL NOT NULL CHECK(price >= 0),
        on_hand INTEGER NOT NULL CHECK(on_hand >= 0),
        reorder_level INTEGER NOT NULL DEFAULT 2 CHECK(reorder_level >= 0),
        location TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))
    )
    """)

    # 3. Customer Orders & Items (EP-04, EP-05)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        subtotal REAL NOT NULL,
        tax REAL NOT NULL,
        total REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Completed',
        FOREIGN KEY (customer_id) REFERENCES users(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_price REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES customer_orders(id),
        FOREIGN KEY (book_id) REFERENCES books(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_ref TEXT UNIQUE NOT NULL,
        order_id INTEGER UNIQUE NOT NULL,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        subtotal REAL NOT NULL,
        tax REAL NOT NULL,
        total REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES customer_orders(id)
    )
    """)

    # 4. Suppliers table (EP-06)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        contact_person TEXT,
        email TEXT,
        phone TEXT,
        address TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 5. Purchase Orders & Line Items (EP-07, EP-08)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_number TEXT UNIQUE NOT NULL,
        supplier_id INTEGER NOT NULL,
        created_by INTEGER NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL CHECK(status IN ('Draft', 'Submitted', 'Partially Received', 'Received', 'Canceled')) DEFAULT 'Draft',
        total_cost REAL NOT NULL DEFAULT 0.0,
        notes TEXT,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS po_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        quantity_ordered INTEGER NOT NULL CHECK(quantity_ordered > 0),
        quantity_received INTEGER NOT NULL DEFAULT 0 CHECK(quantity_received >= 0),
        unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
        FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
        FOREIGN KEY (book_id) REFERENCES books(id)
    )
    """)

    # 6. Audit Logs table (EP-10)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_email TEXT,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id TEXT,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # --- Pre-seed default data if empty ---
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("Admin User", "admin@bookstore.com", generate_password_hash("Admin123!"), "admin"),
            ("Jane Employee", "employee@bookstore.com", generate_password_hash("Employee123!"), "employee"),
            ("Frank Customer", "customer@bookstore.com", generate_password_hash("Customer123!"), "customer"),
        ]
        cursor.executemany("INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)", default_users)

    cursor.execute("SELECT COUNT(*) FROM books")
    if cursor.fetchone()[0] == 0:
        sample_books = [
            ("BK-001", "The Great Gatsby (First Edition 1925)", "F. Scott Fitzgerald", "1st Edition", "Classic Fiction", "Fine", 2450.00, 2, 1, "Rare Vault A-1", 1),
            ("BK-002", "Don Quixote (Leather Bound)", "Miguel de Cervantes", "1880 Edition", "Classic Fiction", "Very Good", 480.00, 4, 2, "Shelf B-3", 1),
            ("BK-003", "Frankenstein; or, The Modern Prometheus", "Mary Shelley", "Colburn and Bentley 1831", "Gothic Horror", "Good", 1850.00, 1, 1, "Rare Vault A-2", 1),
            ("BK-004", "The Hobbit (First American Edition)", "J.R.R. Tolkien", "Houghton Mifflin 1938", "Fantasy", "Fine", 3200.00, 3, 2, "Rare Vault B-1", 1),
            ("BK-005", "Nineteen Eighty-Four", "George Orwell", "Secker & Warburg 1949", "Dystopian", "Fair", 650.00, 5, 2, "Shelf C-1", 1),
            ("BK-006", "Pride and Prejudice (Illustrated)", "Jane Austen", "Peacock Edition 1894", "Classic Fiction", "Very Good", 1200.00, 2, 2, "Shelf A-4", 1),
            ("BK-007", "A Christmas Carol (Early Printing)", "Charles Dickens", "Chapman & Hall 1844", "Classic", "Good", 890.00, 1, 2, "Rare Vault A-3", 1)
        ]
        cursor.executemany("""
            INSERT INTO books (identifier, title, author, edition, category, condition, price, on_hand, reorder_level, location, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sample_books)

    cursor.execute("SELECT COUNT(*) FROM suppliers")
    if cursor.fetchone()[0] == 0:
        sample_suppliers = [
            ("SUP-101", "Antiquarian Book Binderies & Press", "Arthur Pendelton", "orders@antiquarianbindery.com", "(555) 234-8901", "120 Heritage Way, Boston, MA", 1),
            ("SUP-102", "Archival Folio Publishers", "Eleanor Vance", "supply@archivalfolio.com", "(555) 876-5432", "450 Preservation Blvd, Philadelphia, PA", 1),
            ("SUP-103", "Heritage Manuscript Restorations", "Marcus Thorne", "contact@heritagems.com", "(555) 345-6789", "88 Old Print St, New York, NY", 1),
            ("SUP-104", "Discontinued Classic Imports (Legacy)", "Walter Sterling", "info@legacyimports.com", "(555) 999-1122", "14 Harbor Rd, Portland, ME", 0)
        ]
        cursor.executemany("""
            INSERT INTO suppliers (supplier_code, name, contact_person, email, phone, address, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, sample_suppliers)

    db.commit()
    db.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                flash("Please sign in first.", "warning")
                return redirect(url_for("login"))
            if session.get("role") not in allowed_roles:
                flash("Access denied. You do not have permissions for this action.", "danger")
                return redirect(url_for("catalog"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- BASE LAYOUT ---
BASE_LAYOUT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bookstore Management System - Group 6</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { border-radius: 8px; border: 1px solid #dee2e6; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .badge-draft { background-color: #6c757d; }
        .badge-submitted { background-color: #0d6efd; }
        .badge-partially { background-color: #ffc107; color: #000; }
        .badge-received { background-color: #198754; }
        .badge-canceled { background-color: #dc3545; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
    <div class="container">
        <a class="navbar-brand fw-bold" href="{{ url_for('catalog') }}">Rare Bookstore</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMenu">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navMenu">
            <div class="navbar-nav me-auto">
                <a class="nav-link" href="{{ url_for('catalog') }}">Catalog</a>
                {% if session.get('role') in ['employee', 'admin'] %}
                    <a class="nav-link" href="{{ url_for('inventory') }}">Inventory</a>
                    <a class="nav-link" href="{{ url_for('suppliers') }}">Suppliers</a>
                    <a class="nav-link" href="{{ url_for('purchase_orders') }}">Purchase Orders</a>
                    <a class="nav-link" href="{{ url_for('sales') }}">Sales</a>
                    <a class="nav-link" href="{{ url_for('reports') }}">Reports</a>
                {% endif %}
                {% if session.get('role') == 'admin' %}
                    <a class="nav-link text-warning" href="{{ url_for('audit_logs_view') }}">Audit Logs</a>
                {% endif %}
            </div>
            <div class="navbar-nav ms-auto align-items-center">
                <a class="btn btn-outline-light position-relative me-3" href="{{ url_for('view_cart') }}">
                    Cart
                    {% if session.get('cart') %}
                        <span class="badge bg-danger ms-1">{{ session.get('cart')|length }}</span>
                    {% endif %}
                </a>
                {% if session.get('user_id') %}
                    <span class="text-light me-2">{{ session.get('name') }} <span class="badge bg-secondary">{{ session.get('role')|title }}</span></span>
                    <a class="btn btn-outline-danger btn-sm" href="{{ url_for('logout') }}">Sign Out</a>
                {% else %}
                    <a class="nav-link text-light" href="{{ url_for('login') }}">Sign In</a>
                    <a class="btn btn-primary btn-sm ms-2" href="{{ url_for('register') }}">Register</a>
                {% endif %}
            </div>
        </div>
    </div>
</nav>
<div class="container mb-5">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {{ body_content | safe }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

def render_page(inner_content, **kwargs):
    rendered_body = render_template_string(inner_content, **kwargs)
    return render_template_string(BASE_LAYOUT, body_content=rendered_body, **kwargs)

# --- SPRINT 1 CORE ROUTES ---
@app.route("/")
def index():
    return redirect(url_for("catalog"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
        else:
            db = get_db()
            try:
                cur = db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'customer')",
                           (name, email, generate_password_hash(password)))
                db.commit()
                log_audit("REGISTER_USER", "users", cur.lastrowid, f"Registered new customer account: {email}")
                flash("Registration successful! Please sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("An account with this email already exists.", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-5">
            <div class="card p-4">
                <h3 class="fw-bold mb-3 text-center">Create Customer Account</h3>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Full Name</label>
                        <input type="text" name="name" class="form-control" required autofocus>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Email address</label>
                        <input type="email" name="email" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-success w-100">Register</button>
                </form>
                <div class="mt-3 text-center small">
                    Already registered? <a href="{{ url_for('login') }}">Sign In</a>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            log_audit("LOGIN_SUCCESS", "users", user["id"], f"User signed in: {user['email']} ({user['role']})")
            flash(f"Welcome back, {user['name']}! Signed in as {user['role'].title()}.", "success")
            return redirect(url_for("catalog"))
        else:
            flash("Invalid email or password.", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-5">
            <div class="card p-4">
                <h3 class="fw-bold mb-3 text-center">Sign In</h3>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Email address</label>
                        <input type="email" name="email" class="form-control" required autofocus>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Sign In</button>
                </form>
                <div class="mt-3 text-center small">
                    Don't have an account? <a href="{{ url_for('register') }}">Register here</a>
                </div>
                <div class="mt-4 p-3 bg-light rounded small border">
                    <strong>Pre-Seeded Test Credentials:</strong><br>
                    • Admin: admin@bookstore.com / Admin123!<br>
                    • Staff: employee@bookstore.com / Employee123!<br>
                    • Customer: customer@bookstore.com / Customer123!
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT)

@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid:
        log_audit("LOGOUT", "users", uid, f"User signed out: {session.get('email')}")
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("login"))

@app.route("/catalog")
def catalog():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    condition = request.args.get("condition", "").strip()
    in_stock_only = request.args.get("in_stock") == "1"

    sql = "SELECT * FROM books WHERE is_active = 1"
    params = []

    if query:
        sql += " AND (title LIKE ? OR author LIKE ? OR identifier LIKE ?)"
        term = f"%{query}%"
        params.extend([term, term, term])
    if category:
        sql += " AND category = ?"
        params.append(category)
    if condition:
        sql += " AND condition = ?"
        params.append(condition)
    if in_stock_only:
        sql += " AND on_hand > 0"

    sql += " ORDER BY title ASC"

    db = get_db()
    books = db.execute(sql, params).fetchall()
    categories = [r[0] for r in db.execute("SELECT DISTINCT category FROM books WHERE is_active = 1").fetchall()]
    conditions = [r[0] for r in db.execute("SELECT DISTINCT condition FROM books WHERE is_active = 1").fetchall()]

    CONTENT = """
    <div class="row mb-4">
        <div class="col-12">
            <h2 class="fw-bold">Rare Book Catalog</h2>
            <p class="text-muted">Browse, filter, and discover rare first editions and antiquarian volumes.</p>
        </div>
        <div class="col-12">
            <form method="GET" action="{{ url_for('catalog') }}" class="card p-3 bg-white">
                <div class="row g-2">
                    <div class="col-md-4">
                        <input type="text" name="q" class="form-control" placeholder="Search title, author, SKU..." value="{{ selected_q }}">
                    </div>
                    <div class="col-md-3">
                        <select name="category" class="form-select">
                            <option value="">All Categories</option>
                            {% for cat in categories %}
                                <option value="{{ cat }}" {% if selected_cat == cat %}selected{% endif %}>{{ cat }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-2">
                        <select name="condition" class="form-select">
                            <option value="">All Conditions</option>
                            {% for cond in conditions %}
                                <option value="{{ cond }}" {% if selected_cond == cond %}selected{% endif %}>{{ cond }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-2 d-flex align-items-center">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" name="in_stock" value="1" id="inStock" {% if in_stock_only %}checked{% endif %}>
                            <label class="form-check-label" for="inStock">In-Stock Only</label>
                        </div>
                    </div>
                    <div class="col-md-1">
                        <button type="submit" class="btn btn-primary w-100">Filter</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    <div class="row">
        {% if books %}
            {% for b in books %}
                <div class="col-md-4 mb-4">
                    <div class="card h-100">
                        <div class="card-body d-flex flex-column">
                            <div class="d-flex justify-content-between mb-2">
                                <span class="badge bg-secondary">{{ b.category }}</span>
                                {% if b.on_hand <= b.reorder_level and b.on_hand > 0 %}
                                    <span class="badge bg-warning text-dark">Low Stock ({{ b.on_hand }} left)</span>
                                {% elif b.on_hand > 0 %}
                                    <span class="badge bg-success">In Stock ({{ b.on_hand }})</span>
                                {% else %}
                                    <span class="badge bg-danger">Out of Stock</span>
                                {% endif %}
                            </div>
                            <h5 class="fw-bold">{{ b.title }}</h5>
                            <h6 class="text-muted">By {{ b.author }}</h6>
                            <p class="small mb-1"><strong>SKU:</strong> <code>{{ b.identifier }}</code></p>
                            <p class="small mb-1"><strong>Condition:</strong> {{ b.condition }}</p>
                            <p class="small mb-3"><strong>Edition:</strong> {{ b.edition or 'Standard' }}</p>
                            <div class="mt-auto d-flex justify-content-between align-items-center">
                                <span class="fs-5 fw-bold text-primary">${{ "%.2f"|format(b.price) }}</span>
                                {% if b.on_hand > 0 %}
                                    <form method="POST" action="{{ url_for('add_to_cart', book_id=b.id) }}">
                                        <button type="submit" class="btn btn-outline-success btn-sm">Add to Cart</button>
                                    </form>
                                {% else %}
                                    <button class="btn btn-secondary btn-sm" disabled>Unavailable</button>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <div class="col-12 text-center py-5">
                <h4 class="text-muted">No books found.</h4>
                <a href="{{ url_for('catalog') }}" class="btn btn-outline-primary mt-2">Clear Filters</a>
            </div>
        {% endif %}
    </div>
    """
    return render_page(CONTENT, books=books, categories=categories, conditions=conditions,
                       selected_q=query, selected_cat=category, selected_cond=condition, in_stock_only=in_stock_only)

@app.route("/inventory")
@role_required(["employee", "admin"])
def inventory():
    db = get_db()
    books = db.execute("SELECT * FROM books ORDER BY id DESC").fetchall()
    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">Book Inventory Management</h2>
            <p class="text-muted mb-0">Authorized Staff View: Track, edit, and deactivate bookstore catalog items.</p>
        </div>
        <a href="{{ url_for('add_book') }}" class="btn btn-success">+ Add New Book</a>
    </div>
    <div class="card p-3">
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>SKU</th>
                    <th>Title & Author</th>
                    <th>Category</th>
                    <th>Price</th>
                    <th>Stock</th>
                    <th>Location</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for b in books %}
                <tr class="{% if not b.is_active %}table-secondary opacity-75{% endif %}">
                    <td><code>{{ b.identifier }}</code></td>
                    <td><strong>{{ b.title }}</strong><br><small class="text-muted">{{ b.author }} ({{ b.condition }})</small></td>
                    <td><span class="badge bg-secondary">{{ b.category }}</span></td>
                    <td>${{ "%.2f"|format(b.price) }}</td>
                    <td>
                        {{ b.on_hand }}
                        {% if b.on_hand <= b.reorder_level %}
                            <span class="badge bg-warning text-dark ms-1">Low (≤{{ b.reorder_level }})</span>
                        {% endif %}
                    </td>
                    <td>{{ b.location or 'N/A' }}</td>
                    <td>{% if b.is_active %}<span class="badge bg-success">Active</span>{% else %}<span class="badge bg-dark">Inactive</span>{% endif %}</td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <a href="{{ url_for('edit_book', book_id=b.id) }}" class="btn btn-outline-primary">Edit</a>
                            <form method="POST" action="{{ url_for('toggle_book', book_id=b.id) }}" class="d-inline">
                                <button type="submit" class="btn btn-outline-warning">
                                    {% if b.is_active %}Deactivate{% else %}Reactivate{% endif %}
                                </button>
                            </form>
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, books=books)

@app.route("/inventory/add", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def add_book():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        edition = request.form.get("edition", "").strip()
        category = request.form.get("category", "").strip()
        condition = request.form.get("condition", "").strip()
        price = float(request.form.get("price", 0.0))
        on_hand = int(request.form.get("on_hand", 0))
        reorder_level = int(request.form.get("reorder_level", 2))
        location = request.form.get("location", "").strip()

        if price < 0 or on_hand < 0 or reorder_level < 0:
            flash("Price, quantity, and reorder levels cannot be negative.", "danger")
        else:
            db = get_db()
            try:
                cur = db.execute("""
                    INSERT INTO books (identifier, title, author, edition, category, condition, price, on_hand, reorder_level, location, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (identifier, title, author, edition, category, condition, price, on_hand, reorder_level, location))
                db.commit()
                log_audit("ADD_BOOK", "books", cur.lastrowid, f"Added book SKU: {identifier} - '{title}'")
                flash("Book added to inventory successfully!", "success")
                return redirect(url_for("inventory"))
            except sqlite3.IntegrityError:
                flash(f"Book identifier '{identifier}' already exists.", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card p-4">
                <h3 class="fw-bold mb-3">Add Book Record</h3>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">SKU / Identifier</label>
                        <input type="text" name="identifier" class="form-control" placeholder="BK-008" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Title</label>
                        <input type="text" name="title" class="form-control" required>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Author</label>
                            <input type="text" name="author" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Edition</label>
                            <input type="text" name="edition" class="form-control" placeholder="1st Edition">
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Category</label>
                            <input type="text" name="category" class="form-control" placeholder="Classic Fiction" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Condition</label>
                            <select name="condition" class="form-select" required>
                                <option value="Fine">Fine</option>
                                <option value="Very Good">Very Good</option>
                                <option value="Good">Good</option>
                                <option value="Fair">Fair</option>
                                <option value="Poor">Poor</option>
                            </select>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Price ($)</label>
                            <input type="number" step="0.01" min="0" name="price" class="form-control" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Stock on Hand</label>
                            <input type="number" min="0" name="on_hand" class="form-control" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Reorder Level</label>
                            <input type="number" min="0" name="reorder_level" class="form-control" value="2">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Storage Location</label>
                        <input type="text" name="location" class="form-control" placeholder="Shelf A-1">
                    </div>
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('inventory') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">Save Book</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT)

@app.route("/inventory/edit/<int:book_id>", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def edit_book(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        flash("Book not found.", "danger")
        return redirect(url_for("inventory"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        edition = request.form.get("edition", "").strip()
        category = request.form.get("category", "").strip()
        condition = request.form.get("condition", "").strip()
        price = float(request.form.get("price", 0.0))
        on_hand = int(request.form.get("on_hand", 0))
        reorder_level = int(request.form.get("reorder_level", 2))
        location = request.form.get("location", "").strip()
        is_active = 1 if request.form.get("is_active") == "1" else 0

        db.execute("""
            UPDATE books
            SET title = ?, author = ?, edition = ?, category = ?, condition = ?, price = ?, on_hand = ?, reorder_level = ?, location = ?, is_active = ?
            WHERE id = ?
        """, (title, author, edition, category, condition, price, on_hand, reorder_level, location, is_active, book_id))
        db.commit()
        log_audit("UPDATE_BOOK", "books", book_id, f"Updated book {book['identifier']} - '{title}'")
        flash("Book record updated successfully.", "success")
        return redirect(url_for("inventory"))

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card p-4">
                <h3 class="fw-bold mb-3">Edit Book: {{ book.title }}</h3>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Title</label>
                        <input type="text" name="title" class="form-control" value="{{ book.title }}" required>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Author</label>
                            <input type="text" name="author" class="form-control" value="{{ book.author }}" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Edition</label>
                            <input type="text" name="edition" class="form-control" value="{{ book.edition or '' }}">
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Category</label>
                            <input type="text" name="category" class="form-control" value="{{ book.category }}" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Condition</label>
                            <select name="condition" class="form-select" required>
                                <option value="Fine" {% if book.condition == 'Fine' %}selected{% endif %}>Fine</option>
                                <option value="Very Good" {% if book.condition == 'Very Good' %}selected{% endif %}>Very Good</option>
                                <option value="Good" {% if book.condition == 'Good' %}selected{% endif %}>Good</option>
                                <option value="Fair" {% if book.condition == 'Fair' %}selected{% endif %}>Fair</option>
                                <option value="Poor" {% if book.condition == 'Poor' %}selected{% endif %}>Poor</option>
                            </select>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Price ($)</label>
                            <input type="number" step="0.01" min="0" name="price" class="form-control" value="{{ book.price }}" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Stock on Hand</label>
                            <input type="number" min="0" name="on_hand" class="form-control" value="{{ book.on_hand }}" required>
                        </div>
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Reorder Level</label>
                            <input type="number" min="0" name="reorder_level" class="form-control" value="{{ book.reorder_level }}">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Storage Location</label>
                        <input type="text" name="location" class="form-control" value="{{ book.location or '' }}">
                    </div>
                    <div class="mb-3 form-check">
                        <input type="checkbox" class="form-check-input" name="is_active" value="1" id="act" {% if book.is_active %}checked{% endif %}>
                        <label class="form-check-label" for="act">Active in catalog</label>
                    </div>
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('inventory') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">Update Book</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT, book=book)

@app.route("/inventory/toggle/<int:book_id>", methods=["POST"])
@role_required(["employee", "admin"])
def toggle_book(book_id):
    db = get_db()
    book = db.execute("SELECT is_active, identifier, title FROM books WHERE id = ?", (book_id,)).fetchone()
    if book:
        new_status = 0 if book["is_active"] == 1 else 1
        db.execute("UPDATE books SET is_active = ? WHERE id = ?", (new_status, book_id))
        db.commit()
        log_audit("TOGGLE_BOOK_STATUS", "books", book_id, f"Changed active status to {new_status} for SKU: {book['identifier']}")
        flash("Book active status toggled.", "info")
    return redirect(url_for("inventory"))

@app.route("/cart")
def view_cart():
    cart = session.get("cart", {})
    cart_items = []
    subtotal = 0.0

    if cart:
        db = get_db()
        placeholders = ",".join("?" for _ in cart.keys())
        books = db.execute(f"SELECT * FROM books WHERE id IN ({placeholders})", list(cart.keys())).fetchall()
        for b in books:
            qty = cart[str(b["id"])]
            line_total = b["price"] * qty
            subtotal += line_total
            cart_items.append({"book": b, "quantity": qty, "line_total": line_total})

    tax = round(subtotal * 0.06625, 2)
    total = round(subtotal + tax, 2)

    CONTENT = """
    <h2 class="fw-bold mb-3">Shopping Cart</h2>
    {% if cart_items %}
    <div class="row">
        <div class="col-md-8">
            <div class="card p-3 mb-4">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Book</th>
                            <th>Price</th>
                            <th>Quantity</th>
                            <th>Subtotal</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in cart_items %}
                        <tr>
                            <td><strong>{{ item.book.title }}</strong><br><small class="text-muted">{{ item.book.author }}</small></td>
                            <td>${{ "%.2f"|format(item.book.price) }}</td>
                            <td>{{ item.quantity }}</td>
                            <td>${{ "%.2f"|format(item.line_total) }}</td>
                            <td><a href="{{ url_for('remove_from_cart', book_id=item.book.id) }}" class="btn btn-sm btn-outline-danger">Remove</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <a href="{{ url_for('catalog') }}" class="btn btn-outline-secondary">Back to Catalog</a>
        </div>
        <div class="col-md-4">
            <div class="card p-3">
                <h5 class="fw-bold border-bottom pb-2">Order Summary</h5>
                <div class="d-flex justify-content-between my-2"><span>Subtotal:</span><span>${{ "%.2f"|format(subtotal) }}</span></div>
                <div class="d-flex justify-content-between my-2"><span>Estimated Tax (6.625%):</span><span>${{ "%.2f"|format(tax) }}</span></div>
                <div class="d-flex justify-content-between my-2 fs-5 fw-bold border-top pt-2 text-primary"><span>Total:</span><span>${{ "%.2f"|format(total) }}</span></div>
                {% if session.get('user_id') %}
                    <form method="POST" action="{{ url_for('checkout') }}" class="mt-3">
                        <button type="submit" class="btn btn-success w-100 py-2 fw-bold">Confirm & Place Order</button>
                    </form>
                {% else %}
                    <div class="alert alert-info mt-3 p-2 small">
                        Please <a href="{{ url_for('login') }}">sign in</a> to complete checkout.
                    </div>
                {% endif %}
            </div>
        </div>
    </div>
    {% else %}
    <div class="card p-5 text-center">
        <h4>Your cart is empty.</h4>
        <div class="mt-2"><a href="{{ url_for('catalog') }}" class="btn btn-primary">Go to Catalog</a></div>
    </div>
    {% endif %}
    """
    return render_page(CONTENT, cart_items=cart_items, subtotal=subtotal, tax=tax, total=total)

@app.route("/cart/add/<int:book_id>", methods=["POST"])
def add_to_cart(book_id):
    cart = session.get("cart", {})
    str_id = str(book_id)

    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ? AND is_active = 1", (book_id,)).fetchone()
    if not book:
        flash("Book is not available.", "danger")
        return redirect(url_for("catalog"))

    current_qty = cart.get(str_id, 0)
    if current_qty + 1 > book["on_hand"]:
        flash(f"Only {book['on_hand']} copies available.", "warning")
    else:
        cart[str_id] = current_qty + 1
        session["cart"] = cart
        flash(f"Added '{book['title']}' to cart.", "success")

    return redirect(request.referrer or url_for("catalog"))

@app.route("/cart/remove/<int:book_id>")
def remove_from_cart(book_id):
    cart = session.get("cart", {})
    cart.pop(str(book_id), None)
    session["cart"] = cart
    flash("Item removed from cart.", "info")
    return redirect(url_for("view_cart"))

@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    cart = session.get("cart", {})
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("catalog"))

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION")

        subtotal = 0.0
        order_items_data = []

        for book_id_str, qty in cart.items():
            book_id = int(book_id_str)
            book = cursor.execute("SELECT * FROM books WHERE id = ? AND is_active = 1", (book_id,)).fetchone()
            if not book:
                raise ValueError(f"Book ID {book_id} is no longer available.")
            if book["on_hand"] < qty:
                raise ValueError(f"Insufficient stock for '{book['title']}'. Only {book['on_hand']} left.")

            line_total = book["price"] * qty
            subtotal += line_total
            order_items_data.append((book_id, qty, book["price"]))

        tax = round(subtotal * 0.06625, 2)
        total = round(subtotal + tax, 2)
        order_num = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{session['user_id']}"
        trans_ref = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{session['user_id']}"

        cursor.execute("""
            INSERT INTO customer_orders (order_number, customer_id, subtotal, tax, total, status)
            VALUES (?, ?, ?, ?, ?, 'Completed')
        """, (order_num, session["user_id"], subtotal, tax, total))
        order_id = cursor.lastrowid

        for b_id, qty, unit_p in order_items_data:
            cursor.execute("""
                INSERT INTO order_items (order_id, book_id, quantity, unit_price)
                VALUES (?, ?, ?, ?)
            """, (order_id, b_id, qty, unit_p))

            cursor.execute("UPDATE books SET on_hand = on_hand - ? WHERE id = ?", (qty, b_id))

        cursor.execute("""
            INSERT INTO sales (transaction_ref, order_id, subtotal, tax, total)
            VALUES (?, ?, ?, ?, ?)
        """, (trans_ref, order_id, subtotal, tax, total))

        db.commit()
        session.pop("cart", None)
        log_audit("CHECKOUT_COMPLETE", "customer_orders", order_id, f"Order {order_num} completed. Total: ${total:.2f}")
        flash("Order placed successfully!", "success")
        return redirect(url_for("view_receipt", order_id=order_id))

    except Exception as e:
        db.rollback()
        flash(f"Checkout transaction failed: {str(e)}", "danger")
        return redirect(url_for("view_cart"))

@app.route("/receipt/<int:order_id>")
@login_required
def view_receipt(order_id):
    db = get_db()
    order = db.execute("""
        SELECT co.*, u.name as customer_name, u.email as customer_email, s.transaction_ref
        FROM customer_orders co
        JOIN users u ON co.customer_id = u.id
        LEFT JOIN sales s ON s.order_id = co.id
        WHERE co.id = ?
    """, (order_id,)).fetchone()

    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("catalog"))

    if session.get("role") not in ["employee", "admin"] and session.get("user_id") != order["customer_id"]:
        flash("Access denied to view this receipt.", "danger")
        return redirect(url_for("catalog"))

    items = db.execute("""
        SELECT oi.*, b.title, b.author, b.condition
        FROM order_items oi
        JOIN books b ON oi.book_id = b.id
        WHERE oi.order_id = ?
    """, (order_id,)).fetchall()

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card p-4 bg-white">
                <div class="d-flex justify-content-between border-bottom pb-3 mb-3">
                    <div>
                        <h3 class="fw-bold mb-0">Rare Bookstore Inc.</h3>
                        <small class="text-muted">Centralized Bookstore Prototype</small>
                    </div>
                    <div class="text-end">
                        <h5 class="text-success fw-bold mb-0">Order Completed</h5>
                        <small class="text-muted">Date: {{ order.order_date }}</small>
                    </div>
                </div>
                <div class="row mb-3">
                    <div class="col-6">
                        <h6 class="fw-bold text-muted">Customer</h6>
                        <p class="mb-0"><strong>{{ order.customer_name }}</strong></p>
                        <p class="mb-0 text-muted">{{ order.customer_email }}</p>
                    </div>
                    <div class="col-6 text-end">
                        <h6 class="fw-bold text-muted">References</h6>
                        <p class="mb-0"><strong>Order #:</strong> <code>{{ order.order_number }}</code></p>
                        <p class="mb-0"><strong>Txn Ref:</strong> <code>{{ order.transaction_ref }}</code></p>
                    </div>
                </div>
                <table class="table table-bordered mb-3">
                    <thead class="table-light">
                        <tr>
                            <th>Item Description</th>
                            <th class="text-center">Qty</th>
                            <th class="text-end">Price</th>
                            <th class="text-end">Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in items %}
                        <tr>
                            <td><strong>{{ item.title }}</strong> by {{ item.author }} ({{ item.condition }})</td>
                            <td class="text-center">{{ item.quantity }}</td>
                            <td class="text-end">${{ "%.2f"|format(item.unit_price) }}</td>
                            <td class="text-end">${{ "%.2f"|format(item.unit_price * item.quantity) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                    <tfoot>
                        <tr><td colspan="3" class="text-end fw-bold">Subtotal:</td><td class="text-end">${{ "%.2f"|format(order.subtotal) }}</td></tr>
                        <tr><td colspan="3" class="text-end fw-bold">Tax (6.625%):</td><td class="text-end">${{ "%.2f"|format(order.tax) }}</td></tr>
                        <tr class="table-light fs-5"><td colspan="3" class="text-end fw-bold">Total Paid:</td><td class="text-end fw-bold text-success">${{ "%.2f"|format(order.total) }}</td></tr>
                    </tfoot>
                </table>
                <div class="d-flex justify-content-between pt-3 border-top">
                    <a href="{{ url_for('catalog') }}" class="btn btn-outline-secondary">Back to Catalog</a>
                    <button onclick="window.print()" class="btn btn-primary">Print Receipt</button>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT, order=order, items=items)

@app.route("/sales")
@role_required(["employee", "admin"])
def sales():
    db = get_db()
    sales_list = db.execute("""
        SELECT s.*, co.order_number, u.name as customer_name
        FROM sales s
        JOIN customer_orders co ON s.order_id = co.id
        JOIN users u ON co.customer_id = u.id
        ORDER BY s.completed_at DESC
    """).fetchall()

    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">Sales Records & Transactions</h2>
            <p class="text-muted mb-0">Authorized Staff View: Immutable completed sale transactions.</p>
        </div>
    </div>
    <div class="card p-3">
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>Txn Ref</th>
                    <th>Order #</th>
                    <th>Customer</th>
                    <th>Date / Time</th>
                    <th>Total Paid</th>
                    <th>Receipt</th>
                </tr>
            </thead>
            <tbody>
                {% for s in sales %}
                <tr>
                    <td><code>{{ s.transaction_ref }}</code></td>
                    <td><strong>{{ s.order_number }}</strong></td>
                    <td>{{ s.customer_name }}</td>
                    <td>{{ s.completed_at }}</td>
                    <td class="fw-bold text-success">${{ "%.2f"|format(s.total) }}</td>
                    <td><a href="{{ url_for('view_receipt', order_id=s.order_id) }}" class="btn btn-sm btn-outline-primary">View Receipt</a></td>
                </tr>
                {% else %}
                <tr><td colspan="6" class="text-center py-4 text-muted">No sales recorded yet.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, sales=sales_list)

# --- SPRINT 2 MODULES ---

# --- EP-06: SUPPLIER MANAGEMENT ---
@app.route("/suppliers")
@role_required(["employee", "admin"])
def suppliers():
    db = get_db()
    suppliers_list = db.execute("SELECT * FROM suppliers ORDER BY is_active DESC, name ASC").fetchall()
    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">Supplier & Vendor Directory (EP-06)</h2>
            <p class="text-muted mb-0">Manage publishing houses, antiquarian binderies, and archival suppliers.</p>
        </div>
        <a href="{{ url_for('add_supplier') }}" class="btn btn-success">+ Add New Supplier</a>
    </div>
    <div class="card p-3">
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>Code</th>
                    <th>Vendor Name</th>
                    <th>Contact Person</th>
                    <th>Email & Phone</th>
                    <th>Address</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for s in suppliers %}
                <tr class="{% if not s.is_active %}table-secondary opacity-75{% endif %}">
                    <td><code>{{ s.supplier_code }}</code></td>
                    <td><strong>{{ s.name }}</strong></td>
                    <td>{{ s.contact_person or 'N/A' }}</td>
                    <td>
                        <small>{{ s.email or 'No email' }}</small><br>
                        <small class="text-muted">{{ s.phone or 'No phone' }}</small>
                    </td>
                    <td><small>{{ s.address or 'N/A' }}</small></td>
                    <td>
                        {% if s.is_active %}
                            <span class="badge bg-success">Active</span>
                        {% else %}
                            <span class="badge bg-dark">Inactive (Archived)</span>
                        {% endif %}
                    </td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <a href="{{ url_for('edit_supplier', supplier_id=s.id) }}" class="btn btn-outline-primary">Edit</a>
                            <form method="POST" action="{{ url_for('toggle_supplier', supplier_id=s.id) }}" class="d-inline">
                                <button type="submit" class="btn btn-outline-warning">
                                    {% if s.is_active %}Deactivate{% else %}Reactivate{% endif %}
                                </button>
                            </form>
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, suppliers=suppliers_list)

@app.route("/suppliers/add", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def add_supplier():
    if request.method == "POST":
        code = request.form.get("supplier_code", "").strip().upper()
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact_person", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        if not code or not name:
            flash("Supplier Code and Company Name are required.", "danger")
        else:
            db = get_db()
            try:
                cur = db.execute("""
                    INSERT INTO suppliers (supplier_code, name, contact_person, email, phone, address, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (code, name, contact, email, phone, address))
                db.commit()
                log_audit("ADD_SUPPLIER", "suppliers", cur.lastrowid, f"Added supplier {code} - {name}")
                flash("Supplier created successfully!", "success")
                return redirect(url_for("suppliers"))
            except sqlite3.IntegrityError:
                flash(f"Supplier code '{code}' already exists.", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card p-4">
                <h3 class="fw-bold mb-3">Add Supplier / Publisher</h3>
                <form method="POST">
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <label class="form-label">Supplier Code</label>
                            <input type="text" name="supplier_code" class="form-control" placeholder="SUP-105" required autofocus>
                        </div>
                        <div class="col-md-8 mb-3">
                            <label class="form-label">Company Name</label>
                            <input type="text" name="name" class="form-control" placeholder="Oxford Archival Editions" required>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Primary Contact Person</label>
                        <input type="text" name="contact_person" class="form-control" placeholder="Full Name">
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Email</label>
                            <input type="email" name="email" class="form-control" placeholder="orders@company.com">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Phone</label>
                            <input type="text" name="phone" class="form-control" placeholder="(555) 000-0000">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Mailing Address</label>
                        <textarea name="address" class="form-control" rows="2" placeholder="Street, City, State, ZIP"></textarea>
                    </div>
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('suppliers') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">Save Supplier</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT)

@app.route("/suppliers/edit/<int:supplier_id>", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def edit_supplier(supplier_id):
    db = get_db()
    supplier = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not supplier:
        flash("Supplier not found.", "danger")
        return redirect(url_for("suppliers"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact_person", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        is_active = 1 if request.form.get("is_active") == "1" else 0

        db.execute("""
            UPDATE suppliers
            SET name = ?, contact_person = ?, email = ?, phone = ?, address = ?, is_active = ?
            WHERE id = ?
        """, (name, contact, email, phone, address, is_active, supplier_id))
        db.commit()
        log_audit("UPDATE_SUPPLIER", "suppliers", supplier_id, f"Updated supplier {supplier['supplier_code']} - {name}")
        flash("Supplier updated successfully.", "success")
        return redirect(url_for("suppliers"))

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card p-4">
                <h3 class="fw-bold mb-3">Edit Supplier: {{ supplier.name }}</h3>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Supplier Code (Immutable)</label>
                        <input type="text" class="form-control bg-light" value="{{ supplier.supplier_code }}" readonly>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Company Name</label>
                        <input type="text" name="name" class="form-control" value="{{ supplier.name }}" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Contact Person</label>
                        <input type="text" name="contact_person" class="form-control" value="{{ supplier.contact_person or '' }}">
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Email</label>
                            <input type="email" name="email" class="form-control" value="{{ supplier.email or '' }}">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Phone</label>
                            <input type="text" name="phone" class="form-control" value="{{ supplier.phone or '' }}">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Address</label>
                        <textarea name="address" class="form-control" rows="2">{{ supplier.address or '' }}</textarea>
                    </div>
                    <div class="mb-3 form-check">
                        <input type="checkbox" class="form-check-input" name="is_active" value="1" id="act" {% if supplier.is_active %}checked{% endif %}>
                        <label class="form-check-label" for="act">Active Supplier (Eligible for new Purchase Orders)</label>
                    </div>
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('suppliers') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">Update Supplier</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT, supplier=supplier)

@app.route("/suppliers/toggle/<int:supplier_id>", methods=["POST"])
@role_required(["employee", "admin"])
def toggle_supplier(supplier_id):
    db = get_db()
    supplier = db.execute("SELECT is_active, supplier_code, name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if supplier:
        new_status = 0 if supplier["is_active"] == 1 else 1
        db.execute("UPDATE suppliers SET is_active = ? WHERE id = ?", (new_status, supplier_id))
        db.commit()
        log_audit("TOGGLE_SUPPLIER_STATUS", "suppliers", supplier_id, f"Changed status to {new_status} for {supplier['supplier_code']}")
        flash(f"Supplier '{supplier['name']}' status updated.", "info")
    return redirect(url_for("suppliers"))

# --- EP-07 & EP-08: PURCHASE ORDERS & RECEIVING ---
@app.route("/purchase_orders")
@role_required(["employee", "admin"])
def purchase_orders():
    db = get_db()
    pos = db.execute("""
        SELECT po.*, s.name as supplier_name, s.supplier_code, u.name as creator_name,
               (SELECT COUNT(*) FROM po_items WHERE po_id = po.id) as item_count,
               (SELECT SUM(quantity_ordered) FROM po_items WHERE po_id = po.id) as total_qty_ordered,
               (SELECT SUM(quantity_received) FROM po_items WHERE po_id = po.id) as total_qty_received
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        JOIN users u ON po.created_by = u.id
        ORDER BY po.id DESC
    """).fetchall()

    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">Purchase Orders & Replenishment (EP-07)</h2>
            <p class="text-muted mb-0">Track supplier procurement, manage workflow stages, and reconcile deliveries.</p>
        </div>
        <a href="{{ url_for('create_purchase_order') }}" class="btn btn-primary">+ Create New Purchase Order</a>
    </div>
    <div class="card p-3">
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>PO Number</th>
                    <th>Supplier</th>
                    <th>Order Date</th>
                    <th>Items / Qty</th>
                    <th>Total Cost</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for p in pos %}
                <tr>
                    <td><code>{{ p.po_number }}</code></td>
                    <td><strong>{{ p.supplier_name }}</strong><br><small class="text-muted">{{ p.supplier_code }}</small></td>
                    <td><small>{{ p.order_date }}</small></td>
                    <td>{{ p.total_qty_received or 0 }} / {{ p.total_qty_ordered or 0 }} units</td>
                    <td class="fw-bold">${{ "%.2f"|format(p.total_cost) }}</td>
                    <td>
                        {% if p.status == 'Draft' %}
                            <span class="badge badge-draft">Draft</span>
                        {% elif p.status == 'Submitted' %}
                            <span class="badge badge-submitted">Submitted</span>
                        {% elif p.status == 'Partially Received' %}
                            <span class="badge badge-partially">Partially Received</span>
                        {% elif p.status == 'Received' %}
                            <span class="badge badge-received">Fully Received</span>
                        {% else %}
                            <span class="badge badge-canceled">Canceled</span>
                        {% endif %}
                    </td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <a href="{{ url_for('view_purchase_order', po_id=p.id) }}" class="btn btn-outline-secondary">View</a>
                            {% if p.status in ['Submitted', 'Partially Received'] %}
                                <a href="{{ url_for('receive_purchase_order', po_id=p.id) }}" class="btn btn-success">Receive Stock</a>
                            {% endif %}
                        </div>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="7" class="text-center py-4 text-muted">No purchase orders found. Create your first PO above.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, pos=pos)

@app.route("/purchase_orders/create", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def create_purchase_order():
    db = get_db()
    suppliers_list = db.execute("SELECT * FROM suppliers WHERE is_active = 1 ORDER BY name ASC").fetchall()
    books_list = db.execute("SELECT * FROM books WHERE is_active = 1 ORDER BY title ASC").fetchall()

    if request.method == "POST":
        supplier_id = request.form.get("supplier_id")
        notes = request.form.get("notes", "").strip()

        # Parse dynamic item lines
        book_ids = request.form.getlist("book_id[]")
        quantities = request.form.getlist("quantity[]")
        costs = request.form.getlist("cost[]")

        if not supplier_id or not book_ids:
            flash("Please select a supplier and add at least one line item.", "danger")
        else:
            try:
                cursor = db.cursor()
                cursor.execute("BEGIN TRANSACTION")

                po_number = f"PO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                total_po_cost = 0.0
                items_to_insert = []

                for b_id, q_val, c_val in zip(book_ids, quantities, costs):
                    b_id = int(b_id)
                    qty = int(q_val)
                    cost = float(c_val)
                    if qty <= 0 or cost < 0:
                        raise ValueError("Quantity must be positive and cost cannot be negative.")
                    line_cost = qty * cost
                    total_po_cost += line_cost
                    items_to_insert.append((b_id, qty, cost))

                cursor.execute("""
                    INSERT INTO purchase_orders (po_number, supplier_id, created_by, status, total_cost, notes)
                    VALUES (?, ?, ?, 'Draft', ?, ?)
                """, (po_number, int(supplier_id), session["user_id"], total_po_cost, notes))
                po_id = cursor.lastrowid

                for b_id, qty, cost in items_to_insert:
                    cursor.execute("""
                        INSERT INTO po_items (po_id, book_id, quantity_ordered, quantity_received, unit_cost)
                        VALUES (?, ?, ?, 0, ?)
                    """, (po_id, b_id, qty, cost))

                db.commit()
                log_audit("CREATE_PURCHASE_ORDER", "purchase_orders", po_id, f"Created PO {po_number} - Total Cost: ${total_po_cost:.2f}")
                flash(f"Purchase order {po_number} created as Draft.", "success")
                return redirect(url_for("view_purchase_order", po_id=po_id))
            except Exception as e:
                db.rollback()
                flash(f"Error creating PO: {str(e)}", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-9">
            <div class="card p-4">
                <h3 class="fw-bold mb-3">Create Purchase Order (EP-07)</h3>
                <form method="POST">
                    <div class="row mb-3">
                        <div class="col-md-6">
                            <label class="form-label fw-bold">Select Active Supplier</label>
                            <select name="supplier_id" class="form-select" required>
                                <option value="">-- Choose Vendor --</option>
                                {% for s in suppliers %}
                                    <option value="{{ s.id }}">{{ s.name }} ({{ s.supplier_code }})</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label fw-bold">Internal Notes / Instructions</label>
                            <input type="text" name="notes" class="form-control" placeholder="Special edition batch, expected delivery timeline...">
                        </div>
                    </div>

                    <h5 class="fw-bold mt-4 border-bottom pb-2">Line Items (Books to Restock)</h5>
                    <div id="itemsContainer">
                        <div class="row g-2 mb-2 item-row">
                            <div class="col-md-5">
                                <select name="book_id[]" class="form-select" required>
                                    <option value="">-- Select Title --</option>
                                    {% for b in books %}
                                        <option value="{{ b.id }}">{{ b.title }} (Current Stock: {{ b.on_hand }})</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div class="col-md-3">
                                <input type="number" name="quantity[]" class="form-control" placeholder="Qty" min="1" value="5" required>
                            </div>
                            <div class="col-md-3">
                                <input type="number" step="0.01" name="cost[]" class="form-control" placeholder="Wholesale Cost ($)" min="0" value="25.00" required>
                            </div>
                            <div class="col-md-1">
                                <button type="button" class="btn btn-outline-danger w-100" onclick="removeRow(this)">X</button>
                            </div>
                        </div>
                    </div>

                    <button type="button" class="btn btn-outline-secondary btn-sm mt-2 mb-4" onclick="addRow()">+ Add Another Line Item</button>

                    <div class="d-flex justify-content-between border-top pt-3">
                        <a href="{{ url_for('purchase_orders') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">Save as Draft Purchase Order</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
    function addRow() {
        const container = document.getElementById('itemsContainer');
        const firstRow = container.querySelector('.item-row');
        const newRow = firstRow.cloneNode(true);
        newRow.querySelector('select').selectedIndex = 0;
        container.appendChild(newRow);
    }
    function removeRow(btn) {
        const rows = document.querySelectorAll('.item-row');
        if (rows.length > 1) {
            btn.closest('.item-row').remove();
        }
    }
    </script>
    """
    return render_page(CONTENT, suppliers=suppliers_list, books=books_list)

@app.route("/purchase_orders/view/<int:po_id>")
@role_required(["employee", "admin"])
def view_purchase_order(po_id):
    db = get_db()
    po = db.execute("""
        SELECT po.*, s.name as supplier_name, s.supplier_code, s.email as supplier_email,
               s.phone as supplier_phone, s.address as supplier_address, u.name as creator_name
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        JOIN users u ON po.created_by = u.id
        WHERE po.id = ?
    """, (po_id,)).fetchone()

    if not po:
        flash("Purchase order not found.", "danger")
        return redirect(url_for("purchase_orders"))

    items = db.execute("""
        SELECT poi.*, b.title, b.identifier, b.author, b.on_hand
        FROM po_items poi
        JOIN books b ON poi.book_id = b.id
        WHERE poi.po_id = ?
    """, (po_id,)).fetchall()

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-9">
            <div class="card p-4 bg-white">
                <div class="d-flex justify-content-between border-bottom pb-3 mb-3">
                    <div>
                        <h3 class="fw-bold mb-0">Rare Bookstore Inc.</h3>
                        <small class="text-muted">Procurement & Replenishment Department</small>
                    </div>
                    <div class="text-end">
                        <h4 class="mb-0"><code>{{ po.po_number }}</code></h4>
                        <span class="badge {% if po.status == 'Received' %}bg-success{% elif po.status == 'Submitted' %}bg-primary{% elif po.status == 'Partially Received' %}bg-warning text-dark{% elif po.status == 'Draft' %}bg-secondary{% else %}bg-danger{% endif %}">
                            {{ po.status }}
                        </span>
                    </div>
                </div>

                <div class="row mb-4">
                    <div class="col-6">
                        <h6 class="fw-bold text-muted">Vendor</h6>
                        <p class="mb-0"><strong>{{ po.supplier_name }}</strong> ({{ po.supplier_code }})</p>
                        <p class="mb-0 small text-muted">{{ po.supplier_email }} | {{ po.supplier_phone }}</p>
                        <p class="mb-0 small text-muted">{{ po.supplier_address }}</p>
                    </div>
                    <div class="col-6 text-end">
                        <h6 class="fw-bold text-muted">Order Details</h6>
                        <p class="mb-0 small"><strong>Created By:</strong> {{ po.creator_name }}</p>
                        <p class="mb-0 small"><strong>Date:</strong> {{ po.order_date }}</p>
                        <p class="mb-0 small"><strong>Notes:</strong> {{ po.notes or 'None' }}</p>
                    </div>
                </div>

                <table class="table table-bordered mb-4">
                    <thead class="table-light">
                        <tr>
                            <th>Book Title & SKU</th>
                            <th class="text-center">Ordered</th>
                            <th class="text-center">Received</th>
                            <th class="text-end">Unit Cost</th>
                            <th class="text-end">Total Line</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in items %}
                        <tr>
                            <td><strong>{{ item.title }}</strong><br><small class="text-muted">SKU: {{ item.identifier }}</small></td>
                            <td class="text-center">{{ item.quantity_ordered }}</td>
                            <td class="text-center">
                                <span class="{% if item.quantity_received >= item.quantity_ordered %}text-success fw-bold{% elif item.quantity_received > 0 %}text-warning fw-bold{% endif %}">
                                    {{ item.quantity_received }}
                                </span>
                            </td>
                            <td class="text-end">${{ "%.2f"|format(item.unit_cost) }}</td>
                            <td class="text-end">${{ "%.2f"|format(item.unit_cost * item.quantity_ordered) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                    <tfoot>
                        <tr class="table-light fs-5">
                            <td colspan="4" class="text-end fw-bold">Total Estimated Cost:</td>
                            <td class="text-end fw-bold text-primary">${{ "%.2f"|format(po.total_cost) }}</td>
                        </tr>
                    </tfoot>
                </table>

                <div class="d-flex justify-content-between pt-3 border-top">
                    <a href="{{ url_for('purchase_orders') }}" class="btn btn-outline-secondary">Back to PO List</a>
                    <div class="btn-group">
                        <button onclick="window.print()" class="btn btn-outline-dark">Print PO</button>
                        {% if po.status == 'Draft' %}
                            <form method="POST" action="{{ url_for('change_po_status', po_id=po.id, new_status='Submitted') }}" class="d-inline ms-2">
                                <button type="submit" class="btn btn-primary">Submit to Supplier</button>
                            </form>
                            <form method="POST" action="{{ url_for('change_po_status', po_id=po.id, new_status='Canceled') }}" class="d-inline ms-2">
                                <button type="submit" class="btn btn-outline-danger">Cancel PO</button>
                            </form>
                        {% elif po.status in ['Submitted', 'Partially Received'] %}
                            <a href="{{ url_for('receive_purchase_order', po_id=po.id) }}" class="btn btn-success ms-2">Receive Shipment</a>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT, po=po, items=items)

@app.route("/purchase_orders/status/<int:po_id>/<new_status>", methods=["POST"])
@role_required(["employee", "admin"])
def change_po_status(po_id, new_status):
    allowed_statuses = ['Submitted', 'Canceled']
    if new_status not in allowed_statuses:
        flash("Invalid status transition.", "danger")
        return redirect(url_for('view_purchase_order', po_id=po_id))

    db = get_db()
    po = db.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if po:
        db.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new_status, po_id))
        db.commit()
        log_audit("CHANGE_PO_STATUS", "purchase_orders", po_id, f"Transitioned {po['po_number']} to {new_status}")
        flash(f"PO status updated to {new_status}.", "success")
    return redirect(url_for('view_purchase_order', po_id=po_id))

# --- EP-08: RECEIVING WORKFLOW ---
@app.route("/purchase_orders/receive/<int:po_id>", methods=["GET", "POST"])
@role_required(["employee", "admin"])
def receive_purchase_order(po_id):
    db = get_db()
    po = db.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not po or po["status"] not in ["Submitted", "Partially Received"]:
        flash("Only Submitted or Partially Received orders can receive stock.", "warning")
        return redirect(url_for("purchase_orders"))

    items = db.execute("""
        SELECT poi.*, b.title, b.identifier, b.on_hand
        FROM po_items poi
        JOIN books b ON poi.book_id = b.id
        WHERE poi.po_id = ?
    """, (po_id,)).fetchall()

    if request.method == "POST":
        cursor = db.cursor()
        try:
            cursor.execute("BEGIN TRANSACTION")
            any_received = False
            total_items = len(items)
            fully_received_items = 0

            for item in items:
                input_name = f"recv_{item['id']}"
                qty_incoming = int(request.form.get(input_name, 0))

                remaining = item["quantity_ordered"] - item["quantity_received"]
                if qty_incoming < 0:
                    raise ValueError(f"Cannot accept negative quantity for '{item['title']}'.")
                if qty_incoming > remaining:
                    raise ValueError(f"Over-receipt prevented: '{item['title']}' only expects {remaining} more copies (attempted {qty_incoming}).")

                if qty_incoming > 0:
                    any_received = True
                    # 1. Increment PO item received count
                    cursor.execute("""
                        UPDATE po_items SET quantity_received = quantity_received + ? WHERE id = ?
                    """, (qty_incoming, item["id"]))

                    # 2. Increment physical bookstore on_hand stock
                    cursor.execute("""
                        UPDATE books SET on_hand = on_hand + ? WHERE id = ?
                    """, (qty_incoming, item["book_id"]))

                # Check if item will now be fully received
                new_total_rec = item["quantity_received"] + qty_incoming
                if new_total_rec >= item["quantity_ordered"]:
                    fully_received_items += 1

            if not any_received:
                flash("No items were checked in. Enter incoming quantities.", "warning")
                return redirect(url_for("receive_purchase_order", po_id=po_id))

            # Determine updated overall PO status
            if fully_received_items == total_items:
                new_po_status = "Received"
            else:
                new_po_status = "Partially Received"

            cursor.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new_po_status, po_id))
            db.commit()

            log_audit("RECEIVE_INVENTORY", "purchase_orders", po_id, f"Received shipment for {po['po_number']}. New Status: {new_po_status}")
            flash(f"Shipment received successfully! Inventory updated. Status: {new_po_status}", "success")
            return redirect(url_for("view_purchase_order", po_id=po_id))

        except Exception as e:
            db.rollback()
            flash(f"Receiving error: {str(e)}", "danger")

    CONTENT = """
    <div class="row justify-content-center">
        <div class="col-md-9">
            <div class="card p-4">
                <h3 class="fw-bold mb-2">Receive Books into Inventory (EP-08)</h3>
                <p class="text-muted">Enter incoming shipment quantities. System automatically reconciles on-hand stock and prevents over-receipt.</p>
                <form method="POST">
                    <div class="mb-3 p-3 bg-light rounded border">
                        <strong>Purchase Order:</strong> <code>{{ po.po_number }}</code> |
                        <strong>Current Status:</strong> <span class="badge bg-primary">{{ po.status }}</span>
                    </div>

                    <table class="table table-bordered align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Book Title</th>
                                <th class="text-center">Ordered</th>
                                <th class="text-center">Previously Recv</th>
                                <th class="text-center">Remaining</th>
                                <th style="width: 160px;" class="text-center bg-warning bg-opacity-25">Now Receiving</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in items %}
                            {% set remaining = item.quantity_ordered - item.quantity_received %}
                            <tr>
                                <td><strong>{{ item.title }}</strong><br><small class="text-muted">SKU: {{ item.identifier }}</small></td>
                                <td class="text-center">{{ item.quantity_ordered }}</td>
                                <td class="text-center">{{ item.quantity_received }}</td>
                                <td class="text-center fw-bold">{{ remaining }}</td>
                                <td>
                                    {% if remaining > 0 %}
                                        <input type="number" name="recv_{{ item.id }}" class="form-control text-center" min="0" max="{{ remaining }}" value="{{ remaining }}">
                                    {% else %}
                                        <span class="badge bg-success w-100 py-2">Complete</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>

                    <div class="d-flex justify-content-between pt-3">
                        <a href="{{ url_for('view_purchase_order', po_id=po.id) }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-success fw-bold">Confirm & Reconcile Inventory</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT, po=po, items=items)

# --- EP-09: ACCOUNTING & BUSINESS REPORTS ---
@app.route("/reports")
@role_required(["employee", "admin"])
def reports():
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    db = get_db()

    # 1. Sales metrics (Filtered by date)
    sales_sql = "SELECT COUNT(*) as txn_count, COALESCE(SUM(subtotal), 0) as gross_subtotal, COALESCE(SUM(tax), 0) as total_tax, COALESCE(SUM(total), 0) as grand_total FROM sales WHERE 1=1"
    sales_params = []
    if start_date:
        sales_sql += " AND date(completed_at) >= date(?)"
        sales_params.append(start_date)
    if end_date:
        sales_sql += " AND date(completed_at) <= date(?)"
        sales_params.append(end_date)

    sales_summary = db.execute(sales_sql, sales_params).fetchone()

    # 2. Procurement PO Costs (Filtered by date)
    po_sql = "SELECT COUNT(*) as po_count, COALESCE(SUM(total_cost), 0) as total_po_spend FROM purchase_orders WHERE status != 'Canceled'"
    po_params = []
    if start_date:
        po_sql += " AND date(order_date) >= date(?)"
        po_params.append(start_date)
    if end_date:
        po_sql += " AND date(order_date) <= date(?)"
        po_params.append(end_date)

    po_summary = db.execute(po_sql, po_params).fetchone()

    # 3. Inventory Valuation (Always reflects current active physical assets)
    inv_valuation = db.execute("""
        SELECT COUNT(*) as total_titles,
               COALESCE(SUM(on_hand), 0) as total_units,
               COALESCE(SUM(on_hand * price), 0) as total_retail_value
        FROM books WHERE is_active = 1
    """).fetchone()

    # 4. Low-Stock Items
    low_stock_books = db.execute("""
        SELECT * FROM books WHERE on_hand <= reorder_level AND is_active = 1 ORDER BY on_hand ASC
    """).fetchall()

    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">Accounting & Operational Reports (EP-09)</h2>
            <p class="text-muted mb-0">Auditable business metrics reconciling sales, taxes, inventory assets, and procurement spend.</p>
        </div>
        <button onclick="window.print()" class="btn btn-outline-dark">Print Report</button>
    </div>

    <!-- Date Range Filter -->
    <div class="card p-3 mb-4 bg-white">
        <form method="GET" action="{{ url_for('reports') }}" class="row g-2 align-items-end">
            <div class="col-md-4">
                <label class="form-label small fw-bold">Report Start Date</label>
                <input type="date" name="start_date" class="form-control" value="{{ start_date }}">
            </div>
            <div class="col-md-4">
                <label class="form-label small fw-bold">Report End Date</label>
                <input type="date" name="end_date" class="form-control" value="{{ end_date }}">
            </div>
            <div class="col-md-2">
                <button type="submit" class="btn btn-primary w-100">Apply Date Filter</button>
            </div>
            <div class="col-md-2">
                <a href="{{ url_for('reports') }}" class="btn btn-outline-secondary w-100">Reset</a>
            </div>
        </form>
    </div>

    <!-- Summary Metrics Cards -->
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="card p-3 bg-white border-start border-4 border-success">
                <h6 class="text-muted text-uppercase small">Gross Sales Revenue</h6>
                <h3 class="fw-bold text-success mb-0">${{ "%.2f"|format(sales_summary.grand_total) }}</h3>
                <small class="text-muted">{{ sales_summary.txn_count }} completed transactions</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-white border-start border-4 border-primary">
                <h6 class="text-muted text-uppercase small">Sales Tax Collected (6.625%)</h6>
                <h3 class="fw-bold text-primary mb-0">${{ "%.2f"|format(sales_summary.total_tax) }}</h3>
                <small class="text-muted">Subtotal: ${{ "%.2f"|format(sales_summary.gross_subtotal) }}</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-white border-start border-4 border-info">
                <h6 class="text-muted text-uppercase small">Inventory Asset Valuation</h6>
                <h3 class="fw-bold text-info mb-0">${{ "%.2f"|format(inv_valuation.total_retail_value) }}</h3>
                <small class="text-muted">{{ inv_valuation.total_units }} units across {{ inv_valuation.total_titles }} titles</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card p-3 bg-white border-start border-4 border-warning">
                <h6 class="text-muted text-uppercase small">Total Procurement Spend</h6>
                <h3 class="fw-bold text-warning text-dark mb-0">${{ "%.2f"|format(po_summary.total_po_spend) }}</h3>
                <small class="text-muted">{{ po_summary.po_count }} active Purchase Orders</small>
            </div>
        </div>
    </div>

    <!-- Low Stock Reorder Alerts -->
    <div class="card p-3">
        <h5 class="fw-bold text-danger mb-3">Reorder Alert: Low-Stock Inventory Items</h5>
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>SKU</th>
                    <th>Book Title & Author</th>
                    <th>Category</th>
                    <th>Unit Price</th>
                    <th>Current Stock</th>
                    <th>Reorder Threshold</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for b in low_stock_books %}
                <tr class="table-warning">
                    <td><code>{{ b.identifier }}</code></td>
                    <td><strong>{{ b.title }}</strong><br><small class="text-muted">{{ b.author }}</small></td>
                    <td><span class="badge bg-secondary">{{ b.category }}</span></td>
                    <td>${{ "%.2f"|format(b.price) }}</td>
                    <td class="fw-bold text-danger">{{ b.on_hand }}</td>
                    <td>{{ b.reorder_level }}</td>
                    <td>
                        <a href="{{ url_for('create_purchase_order') }}" class="btn btn-sm btn-primary">+ Create PO</a>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="7" class="text-center py-3 text-muted">All active inventory is above reorder thresholds.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, sales_summary=sales_summary, inv_valuation=inv_valuation,
                       low_stock_books=low_stock_books, po_summary=po_summary,
                       start_date=start_date, end_date=end_date)

# --- EP-10: AUDIT LOGS & DATA RECOVERY ---
@app.route("/audit_logs")
@role_required(["admin"])
def audit_logs_view():
    db = get_db()
    logs = db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall()
    CONTENT = """
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0">System Audit Trail & Security Logs (EP-10)</h2>
            <p class="text-muted mb-0">Administrator Only: Immutable chronological record of all administrative, financial, and inventory actions.</p>
        </div>
    </div>
    <div class="card p-3">
        <table class="table table-sm table-hover align-middle mb-0">
            <thead class="table-light">
                <tr>
                    <th>Log ID</th>
                    <th>Timestamp</th>
                    <th>Actor (User)</th>
                    <th>Action</th>
                    <th>Entity</th>
                    <th>Record ID</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {% for l in logs %}
                <tr>
                    <td><code>#{{ l.id }}</code></td>
                    <td><small>{{ l.created_at }}</small></td>
                    <td><small>{{ l.user_email }}</small></td>
                    <td><span class="badge bg-secondary">{{ l.action }}</span></td>
                    <td><code>{{ l.entity }}</code></td>
                    <td>{{ l.entity_id or '-' }}</td>
                    <td><small>{{ l.details or '' }}</small></td>
                </tr>
                {% else %}
                <tr><td colspan="7" class="text-center py-4 text-muted">No audit events recorded yet.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page(CONTENT, logs=logs)

# --- SERVER STARTUP ---
init_db()
print("==================================================================", flush=True)
print("Database initialized successfully with Sprint 1 & Sprint 2 schemas.", flush=True)
print("Bookstore Management System (Sprint 2) is LIVE on: http://127.0.0.1:5050", flush=True)
print("==================================================================", flush=True)
try:
    webbrowser.open("http://127.0.0.1:5050")
except Exception:
    pass

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)