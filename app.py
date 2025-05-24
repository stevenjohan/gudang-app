from flask import Flask, render_template, request, redirect, session, send_file
import mysql.connector
from mysql.connector import pooling
import pandas as pd
import io
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')

# Database connection pool configuration
db_config = {
    'host': os.environ.get('MYSQLHOST'),
    'user': os.environ.get('MYSQLUSER'),
    'password': os.environ.get('MYSQLPASSWORD'),
    'database': os.environ.get('MYSQLDATABASE'),
    'port': int(os.environ.get('MYSQLPORT', 3306)),
    'autocommit': True,
    'pool_name': 'mypool',
    'pool_size': 10,
    'pool_reset_session': True,
    'connect_timeout': 10,
    'sql_mode': 'TRADITIONAL'
}

# Initialize connection pool
try:
    connection_pool = mysql.connector.pooling.MySQLConnectionPool(**db_config)
    logger.info("✅ Database connection pool initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize connection pool: {str(e)}")
    connection_pool = None

def get_connection():
    """Get database connection from pool"""
    try:
        if connection_pool:
            conn = connection_pool.get_connection()
            return conn
        else:
            # Fallback to direct connection
            conn = mysql.connector.connect(
                host=os.environ.get('MYSQLHOST'),
                user=os.environ.get('MYSQLUSER'),
                password=os.environ.get('MYSQLPASSWORD'),
                database=os.environ.get('MYSQLDATABASE'),
                port=int(os.environ.get('MYSQLPORT', 3306)),
                connect_timeout=10,
                autocommit=True
            )
            return conn
    except Exception as e:
        logger.error(f"❌ Database connection failed: {str(e)}")
        raise

# Health check endpoint for Railway
@app.route('/health')
def health_check():
    """Health check endpoint for Railway"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return {'status': 'healthy', 'database': 'connected'}, 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {'status': 'unhealthy', 'error': str(e)}, 500

@app.route('/debug-env')
def debug_env():
    """Route to check environment variables"""
    if app.debug:  # Only in debug mode
        return {
            'MYSQLHOST': bool(os.getenv('MYSQLHOST')),
            'MYSQLUSER': bool(os.getenv('MYSQLUSER')),
            'MYSQLDATABASE': bool(os.getenv('MYSQLDATABASE')),
            'MYSQLPORT': os.getenv('MYSQLPORT'),
            'SECRET_KEY': bool(os.getenv('SECRET_KEY')),
            'PORT': os.getenv('PORT')
        }
    return {'error': 'Debug mode disabled'}, 403

@app.route('/init-db')
def init_db():
    """Initialize database tables and create admin user"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create user table with indexes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user',
                INDEX idx_username (username)
            ) ENGINE=InnoDB
        """)
        
        # Create transaksi table with indexes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaksi (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tanggal DATETIME NOT NULL,
                barang VARCHAR(100) NOT NULL,
                jumlah INT NOT NULL,
                tipe ENUM('masuk', 'keluar') NOT NULL,
                gudang INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'tersedia',
                INDEX idx_barang (barang),
                INDEX idx_tanggal (tanggal),
                INDEX idx_barang_tipe_status (barang, tipe, status),
                INDEX idx_gudang (gudang)
            ) ENGINE=InnoDB
        """)
        
        # Create admin user with hashed password
        admin_password = generate_password_hash('admin123!')  # Use stronger password
        
        cursor.execute("""
            INSERT IGNORE INTO user (username, password, role)
            VALUES ('admin', %s, 'admin')
        """, (admin_password,))
        
        cursor.close()
        conn.close()
        
        logger.info("Database initialized successfully")
        return "Database initialized successfully! Admin user created."
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return f"Error initializing database: {str(e)}", 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('login.html', error="Username and password required")

        try:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Use prepared statement for security
            cursor.execute("SELECT username, password, role FROM user WHERE username = %s LIMIT 1", (username,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()

            if user and check_password_hash(user['password'], password):
                session['username'] = user['username']
                session['role'] = user['role']
                logger.info(f"User {username} logged in successfully")
                return redirect('/')
            
            logger.warning(f"Failed login attempt for username: {username}")
            return render_template('login.html', error="Invalid credentials")
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return render_template('login.html', error="Database connection error")

    return render_template('login.html')

@app.route('/logout')
def logout():
    username = session.get('username')
    session.clear()
    logger.info(f"User {username} logged out")
    return redirect('/login')

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' not in session:
        return redirect('/login')
    
    error = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
            if session.get('role') != 'admin':
                error = "Role Anda tidak diizinkan untuk input data."
            else:
                tanggal = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                barang = request.form.get('barang', '').strip()
                jumlah = int(request.form.get('jumlah', 0))
                tipe = request.form.get('tipe', '')

                if not barang or jumlah <= 0:
                    error = "Data barang dan jumlah harus diisi dengan benar"
                elif tipe == 'masuk':
                    gudang = int(request.form.get('gudang', 0))
                    cursor.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                                 VALUES (%s, %s, %s, %s, %s, %s)''',
                              (tanggal, barang, jumlah, tipe, gudang, 'tersedia'))
                elif tipe == 'keluar':
                    sisa = jumlah
                    cursor.execute('''SELECT id, jumlah, gudang FROM transaksi 
                                 WHERE barang=%s AND tipe='masuk' AND status='tersedia'
                                 ORDER BY tanggal ASC''', (barang,))
                    stok_tersedia = cursor.fetchall()
                    
                    if not stok_tersedia:
                        error = f"Stok tidak tersedia untuk barang: {barang}"
                    else:
                        for stok in stok_tersedia:
                            id_trans, jumlah_stok, gudang_stok = stok
                            if jumlah_stok <= sisa:
                                cursor.execute("UPDATE transaksi SET status='keluar' WHERE id=%s", (id_trans,))
                                cursor.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                                             VALUES (%s, %s, %s, %s, %s, %s)''',
                                          (tanggal, barang, jumlah_stok, 'keluar', gudang_stok, 'keluar'))
                                sisa -= jumlah_stok
                            else:
                                cursor.execute("UPDATE transaksi SET jumlah=%s WHERE id=%s", (jumlah_stok - sisa, id_trans))
                                cursor.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                                             VALUES (%s, %s, %s, %s, %s, %s)''',
                                          (tanggal, barang, sisa, 'keluar', gudang_stok, 'keluar'))
                                sisa = 0
                            if sisa == 0:
                                break
                        
                        if sisa > 0:
                            error = f"Stok tidak mencukupi untuk barang: {barang}"

        if not error and request.method == 'POST':
            cursor.close()
            conn.close()
            return redirect('/')

        # Fetch data with pagination for better performance
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        cursor.execute("SELECT * FROM transaksi ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset))
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return render_template('index.html', data=data, error=error)

    except Exception as e:
        logger.error(f"Index route error: {str(e)}")
        return render_template('index.html', data=[], error="Terjadi kesalahan sistem")

@app.route('/cari', methods=['GET', 'POST'])
def cari():
    if 'username' not in session:
        return redirect('/login')

    hasil = []
    barang = ""
    
    if request.method == 'POST':
        barang = request.form.get('barang', '').strip()
        if barang:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('''SELECT gudang, jumlah, tanggal FROM transaksi
                             WHERE barang=%s AND tipe='masuk' AND status='tersedia'
                             ORDER BY tanggal ASC''', (barang,))
                hasil = cursor.fetchall()
                cursor.close()
                conn.close()
            except Exception as e:
                logger.error(f"Search error: {str(e)}")
                
    return render_template('cari.html', hasil=hasil, barang=barang)

@app.route('/export')
def export_excel():
    if 'username' not in session:
        return redirect('/login')

    try:
        conn = get_connection()
        df = pd.read_sql("SELECT * FROM transaksi ORDER BY id DESC", conn)
        conn.close()

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Riwayat')

        output.seek(0)
        return send_file(output, download_name='riwayat_gudang.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Export error: {str(e)}")
        return "Error exporting data", 500

@app.route('/gudang/<nama_gudang>')
def lihat_gudang(nama_gudang):
    if 'username' not in session:
        return redirect('/login')
        
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT barang, 
                   SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE 0 END) -
                   SUM(CASE WHEN tipe = 'keluar' THEN jumlah ELSE 0 END) AS stok
            FROM transaksi
            WHERE gudang = %s
            GROUP BY barang
            HAVING stok > 0
            ORDER BY barang
        ''', (nama_gudang,))

        barang_list = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('gudang.html', gudang=nama_gudang, barang_list=barang_list)
    except Exception as e:
        logger.error(f"Gudang view error: {str(e)}")
        return "Error loading warehouse data", 500

@app.route('/test-connection')
def test_connection():
    """Test database connection"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return f"✅ Database connection successful! Test query result: {result}"
    except Exception as e:
        return f"❌ Database connection failed: {str(e)}", 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return render_template('error.html', error="Internal server error"), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Disable debug in production for better performance
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)