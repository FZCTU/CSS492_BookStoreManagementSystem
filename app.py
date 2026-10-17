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

# Database file placed in current working directory
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

def init_db():
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

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

# --- ALL HTML TEMPLATES EMBEDDED DIRECTLY IN MEMORY ---
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
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
    <div class="container">
        <a class="navbar-brand fw-bold" href="{{ url_for('catalog') }}">📚 Rare Bookstore</a>
        <div class="navbar-nav me-auto">
            <a class="nav-link" href="{{ url_for('catalog') }}">Catalog</a>
            {% if session.get('role') in ['employee', 'admin'] %}
                <a class="nav-link" href="{{ url_for('inventory') }}">Manage Inventory</a>
                <a class="nav-link" href="{{ url_for('sales') }}">Sales History</a>
            {% endif %}
        </div>
        <div class="navbar-nav ms-auto align-items-center">
            <a class="btn btn-outline-light position-relative me-3" href="{{ url_for('view_cart') }}">
                🛒 Cart
                {% if session.get('cart') %}
                    <span class="badge bg-danger ms-1">{{ session.get('cart')|length }}</span>
                {% endif %}
            </a>
            {% if session.get('user_id') %}
                <span class="text-light me-2">👤 {{ session.get('name') }} <span class="badge bg-secondary">{{ session.get('role')|title }}</span></span>
                <a class="btn btn-outline-danger btn-sm" href="{{ url_for('logout') }}">Sign Out</a>
            {% else %}
                <a class="nav-link text-light" href="{{ url_for('login') }}">Sign In</a>
                <a class="btn btn-primary btn-sm ms-2" href="{{ url_for('register') }}">Register</a>
            {% endif %}
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

# --- ROUTES ---

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
                db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'customer')",
                           (name, email, generate_password_hash(password)))
                db.commit()
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
                    • <em>Admin:</em> admin@bookstore.com / Admin123!<br>
                    • <em>Staff:</em> employee@bookstore.com / Employee123!<br>
                    • <em>Customer:</em> customer@bookstore.com / Customer123!
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(CONTENT)

@app.route("/logout")
def logout():
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
                    <td>{{ b.on_hand }} (Reorder: {{ b.reorder_level }})</td>
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
                db.execute("""
                    INSERT INTO books (identifier, title, author, edition, category, condition, price, on_hand, reorder_level, location, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (identifier, title, author, edition, category, condition, price, on_hand, reorder_level, location))
                db.commit()
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
    book = db.execute("SELECT is_active FROM books WHERE id = ?", (book_id,)).fetchone()
    if book:
        new_status = 0 if book["is_active"] == 1 else 1
        db.execute("UPDATE books SET is_active = ? WHERE id = ?", (new_status, book_id))
        db.commit()
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
            <a href="{{ url_for('catalog') }}" class="btn btn-outline-secondary">← Continue Shopping</a>
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
                        <h3 class="fw-bold mb-0">📚 Rare Bookstore Inc.</h3>
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
                    <a href="{{ url_for('catalog') }}" class="btn btn-outline-secondary">← Back to Catalog</a>
                    <button onclick="window.print()" class="btn btn-primary">🖨️ Print Receipt</button>
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

if __name__ == "__main__":
    init_db()
    print("==================================================================")
    print("Database initialized successfully.")
    print("Bookstore Management System is LIVE on: http://127.0.0.1:5000")
    print("==================================================================")
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass
    app.run(debug=False, host="127.0.0.1", port=5000)