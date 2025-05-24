import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, send_file, flash
from mysql.connector import pooling
import pandas as pd
import io
from werkzeug.security import generate_password_hash, check_password_hash
from flask_caching import Cache

# =============================================
# INITIALIZATION
# =============================================
app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-please-change')

# Cache Configuration
cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})
cache.init_app(app)

# Database Pool Configuration
db_config = {
    "host": os.environ.get('MYSQLHOST', 'mysql.railway.internal'),
    "user": os.environ.get('MYSQLUSER', 'root'),
    "password": os.environ.get('MYSQLPASSWORD'),
    "database": os.environ.get('MYSQLDATABASE', 'railway'),
    "port": int(os.environ.get('MYSQLPORT', 3306)),
    "pool_name": "gudang_pool",
    "pool_size": 5,
    "autocommit": True
}

try:
    connection_pool = pooling.MySQLConnectionPool(**db_config)
    print("✅ Database connection pool created successfully")
except Exception as e:
    print(f"❌ Failed to create connection pool: {str(e)}")
    raise

# =============================================
# HELPER FUNCTIONS
# =============================================
def get_connection():
    """Get database connection from pool"""
    return connection_pool.get_connection()

def execute_query(query, params=None, fetch_one=False):
    """Execute SQL query with proper connection handling"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        
        if fetch_one:
            return cursor.fetchone()
        return cursor.fetchall()
        
    except Exception as e:
        print(f"Database error: {str(e)}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# =============================================
# ROUTES
# =============================================
@app.route('/init-db')
def init_db():
    """Initialize database structure"""
    try:
        # Create tables
        execute_query("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role ENUM('admin', 'user') DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        execute_query("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tanggal DATETIME NOT NULL,
                barang VARCHAR(100) NOT NULL,
                jumlah INT NOT NULL,
                tipe ENUM('masuk', 'keluar') NOT NULL,
                gudang VARCHAR(50) NOT NULL,
                status ENUM('tersedia', 'keluar') DEFAULT 'tersedia',
                user_id INT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                INDEX idx_barang (barang),
                INDEX idx_tipe_status (tipe, status),
                INDEX idx_gudang (gudang),
                INDEX idx_tanggal (tanggal)
            )
        """)
        
        # Create admin user if not exists
        admin_exists = execute_query(
            "SELECT 1 FROM users WHERE username = 'admin'", 
            fetch_one=True
        )
        
        if not admin_exists:
            hashed_pw = generate_password_hash('admin123')
            execute_query(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                ('admin', hashed_pw, 'admin')
            )
        
        return "Database initialized successfully! Admin user: admin / admin123"
    
    except Exception as e:
        return f"Initialization failed: {str(e)}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = execute_query(
            "SELECT id, username, password, role FROM users WHERE username = %s",
            (username,),
            fetch_one=True
        )
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect('/')
        
        flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect('/login')

@app.route('/')
@cache.cached(timeout=30)
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    transactions = execute_query(
        "SELECT * FROM transactions ORDER BY tanggal DESC LIMIT %s OFFSET %s",
        (per_page, offset)
    )
    
    total_items = execute_query(
        "SELECT COUNT(*) as count FROM transactions",
        fetch_one=True
    )['count']
    
    return render_template(
        'dashboard.html',
        transactions=transactions,
        page=page,
        per_page=per_page,
        total_items=total_items
    )

@app.route('/transaksi/barang-masuk', methods=['POST'])
def barang_masuk():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect('/')
    
    try:
        execute_query(
            """
            INSERT INTO transactions 
            (tanggal, barang, jumlah, tipe, gudang, user_id)
            VALUES (%s, %s, %s, 'masuk', %s, %s)
            """,
            (
                datetime.now(),
                request.form.get('barang'),
                int(request.form.get('jumlah')),
                request.form.get('gudang'),
                session['user_id']
            )
        )
        cache.clear()
        flash('Item added successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect('/')

@app.route('/transaksi/barang-keluar', methods=['POST'])
def barang_keluar():
    if 'user_id' not in session:
        return redirect('/login')
    
    # Implement your inventory deduction logic here
    # ...
    
    cache.clear()
    return redirect('/')

@app.route('/export/excel')
def export_excel():
    if 'user_id' not in session:
        return redirect('/login')
    
    data = execute_query("SELECT * FROM transactions ORDER BY tanggal DESC")
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transactions')
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='inventory_report.xlsx',
        as_attachment=True
    )

# =============================================
# ERROR HANDLERS
# =============================================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# =============================================
# MAIN EXECUTION
# =============================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', False))