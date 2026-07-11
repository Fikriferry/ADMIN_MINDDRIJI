import os
import uuid
import random
from functools import wraps
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Blueprint
from flask_cors import CORS
from flask_mail import Mail, Message
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import re
from collections import Counter
from datetime import datetime
from bson.objectid import ObjectId
import threading

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback-secret-key')

# ── CONFIGURATION SUPABASE CLIENTS ───────────────────────────
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Client service role — untuk bypass RLS pada dashboard admin
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY', SUPABASE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── CONFIGURATION FLASK-MAIL (TUKANG POS OTP) ────────────────
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_USERNAME")
mail = Mail(app)

# ── CONFIGURATION MONGODB CLIENT (GUDANG HASIL SCRAPING) ─────
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017') 
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client["mind_driji"] # Nama database MongoDB kamu
mongo_collection = mongo_db["artikel_doomscrolling"]

# ── DATA DUMMY DASHBOARD WEB ADMIN ───────────────────────────
NOTIFIKASI = [
    {"id": 1, "judul": "Pengguna baru terdaftar",      "isi": "Fajar Rahman baru saja mendaftar.",             "waktu": "2 menit lalu",   "tipe": "info",    "dibaca": False},
    {"id": 2, "judul": "AI Insight selesai diproses",  "isi": "Laporan insight untuk 45 pengguna selesai.",    "waktu": "15 menit lalu",  "tipe": "success", "dibaca": False},
    {"id": 3, "judul": "Peringatan penggunaan sistem", "isi": "Memori server mencapai 78%.",                    "waktu": "1 jam lalu",     "tipe": "warning", "dibaca": False},
    {"id": 4, "judul": "Artikel baru dipublikasi",     "isi": "Artikel 'Stres di Era Digital' dipublikasi.",   "waktu": "3 jam lalu",     "tipe": "info",    "dibaca": True},
    {"id": 5, "judul": "Pemain baru terdaftar",        "isi": "Patch v2.3.1 berhasil diterapkan.",             "waktu": "Kemarin, 22:04", "tipe": "success", "dibaca": True},
    {"id": 6, "judul": "Laporan mingguan siap",        "isi": "Ringkasan aktivitas minggu ini tersedia.",      "waktu": "2 hari lalu",    "tipe": "info",    "dibaca": True},
]

ARTIKEL = [
    {"id": 1, "judul": "Mengelola Stres di Era Digital",      "kategori": "Kesehatan Mental", "penulis": "dr. Budi", "tanggal": "14 Mei 2024", "status": "Publikasi", "views": 1240},
    {"id": 2, "judul": "Mindfulness untuk Produktivitas",     "kategori": "Mindfulness",      "penulis": "dr. Hendra","tanggal": "10 Mei 2024", "status": "Publikasi", "views": 876},
    {"id": 3, "judul": "Tanda-tanda Burnout dan Cara Atasi",  "kategori": "Kesehatan Mental", "penulis": "Admin",     "tanggal": "07 Mei 2024", "status": "Draft",     "views": 0},
    {"id": 4, "judul": "Peran AI dalam Kesehatan Mental",     "kategori": "Teknologi AI",     "penulis": "Admin",     "tanggal": "03 Mei 2024", "status": "Publikasi", "views": 2105},
    {"id": 5, "judul": "Teknik Pernapasan untuk Relaksasi",   "kategori": "Mindfulness",      "penulis": "dr. Budi",  "tanggal": "28 Apr 2024", "status": "Review",    "views": 0},
    {"id": 6, "judul": "Hubungan Tidur dan Kesehatan Mental", "kategori": "Gaya Hidup",       "penulis": "dr. Hendra","tanggal": "22 Apr 2024", "status": "Publikasi", "views": 654},
]
print("MAIL_USERNAME =", os.getenv("MAIL_USERNAME"))
print("MAIL_PASSWORD =", os.getenv("MAIL_PASSWORD"))

# ── WEB ADMIN AUTH HELPERS ───────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_email' not in session:
            flash('Silakan login terlebih dahulu.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def do_supabase_login(email, password):
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = resp.user
        if not user:
            return {'ok': False, 'error': 'Email atau password salah.'}

        nama   = email.split('@')[0].title()
        role   = 'Admin'
        avatar = nama[0].upper()

        try:
            p = supabase_admin.table('admin_users').select('nama,role,avatar').eq('email', email).single().execute()
            if p.data:
                nama   = p.data.get('nama', nama)
                role   = p.data.get('role', role)
                avatar = p.data.get('avatar', avatar)
        except Exception:
            pass

        return {'ok': True, 'email': email, 'nama': nama, 'role': role, 'avatar': avatar, 'uid': str(user.id)}
    except Exception as e:
        msg = str(e)
        if 'Invalid login credentials' in msg or 'invalid_credentials' in msg:
            return {'ok': False, 'error': 'Email atau password salah.'}
        if 'Email not confirmed' in msg:
            return {'ok': False, 'error': 'Email belum dikonfirmasi. Cek inbox Anda.'}
        if 'too many requests' in msg.lower():
            return {'ok': False, 'error': 'Terlalu banyak percobaan. Tunggu beberapa menit.'}
        return {'ok': False, 'error': 'Terjadi kesalahan. Silakan coba lagi.'}

# ── FORMATTING & CALCULATION HELPERS ─────────────────────────
def format_tanggal(iso_str):
    if not iso_str:
        return '-'
    try:
        bulan = ['','Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des']
        tgl = iso_str[:10]
        y, m, d = tgl.split('-')
        return f"{int(d)} {bulan[int(m)]} {y}"
    except Exception:
        return iso_str

def hitung_usia(tanggal_lahir_str):
    if not tanggal_lahir_str:
        return '-'
    try:
        tgl = tanggal_lahir_str[:10]
        y, m, d = map(int, tgl.split('-'))
        lahir = date(y, m, d)
        hari_ini = date.today()
        usia = hari_ini.year - lahir.year - ((hari_ini.month, hari_ini.day) < (lahir.month, lahir.day))
        return f"{usia} thn"
    except Exception:
        return '-'

def get_all_pengguna():
    try:
        resp = (
            supabase_admin
            .table('profiles')
            .select('id, nama_lengkap, email, no_hp, tanggal_lahir, jenis_kelamin, avatar_url, created_at, is_verified')
            .order('created_at', desc=True)
            .execute()
        )
        rows = resp.data or []

        pengguna = []
        for row in rows:
            nama = row.get('nama_lengkap') or row.get('email', '').split('@')[0].title()
            pengguna.append({
                'id':             row.get('id', ''),
                'nama_lengkap':   nama,
                'email':          row.get('email', '-'),
                'no_hp':          row.get('no_hp') or '-',
                'tanggal_lahir':  format_tanggal(row.get('tanggal_lahir')),
                'jenis_kelamin':  row.get('jenis_kelamin') or '-',
                'avatar_url':     row.get('avatar_url'),
                'avatar_letter':  nama[0].upper() if nama else '?',
                'bergabung':      format_tanggal(row.get('created_at')),
                'usia':           hitung_usia(row.get('tanggal_lahir')),
                'is_verified':    row.get('is_verified', False)
            })
        return pengguna, None
    except Exception as e:
        return [], f"Gagal memuat data pengguna: {str(e)[:120]}"


# ── INTERFACE API MOBILE (FLUTTER) ───────────────────────────

@app.route('/otp-test')
def otp_test():
    try:
        msg = Message(
            'Tes OTP MIND DRIJI',
            recipients=['minddrijiapp@gmail.com']
        )

        msg.body = '''
Halo,

Ini adalah email test dari MIND DRIJI.

Jika email ini masuk berarti SMTP Gmail berhasil.
'''

        mail.send(msg)

        return jsonify({
            "status": "success",
            "message": "Email berhasil dikirim"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })

# ➡️ 2. API VERIFIKASI OTP (AKTIVASI AKUN)
@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    try:
        data = request.get_json()

        email = data.get('email')
        otp = data.get('otp')

        result = supabase_admin.table(
            'email_otps'
        ).select('*').eq(
            'email', email
        ).execute()

        if not result.data:
            return jsonify({
                "status": "error",
                "message": "OTP tidak ditemukan"
            }), 404

        otp_data = result.data[0]

        if otp_data["is_used"]:
            return jsonify({
                "status": "error",
                "message": "OTP sudah digunakan"
            }), 400

        if otp_data["otp_code"] != otp:
            return jsonify({
                "status": "error",
                "message": "OTP salah"
            }), 400

        expires_at = datetime.fromisoformat(
            otp_data["expires_at"].replace(
                "Z", "+00:00"
            )
        )

        if datetime.utcnow() > expires_at.replace(tzinfo=None):
            return jsonify({
                "status": "error",
                "message": "OTP sudah kadaluarsa"
            }), 400

        supabase_admin.table(
            'email_otps'
        ).update({
            "is_used": True
        }).eq(
            'email', email
        ).execute()

        return jsonify({
            "status": "success",
            "message": "OTP valid"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    try:
        data = request.get_json()

        email = data.get('email')

        if not email:
            return jsonify({
                "status": "error",
                "message": "Email wajib diisi"
            }), 400

        otp_code = str(random.randint(100000, 999999))

        expires_at = (
            datetime.utcnow() +
            timedelta(minutes=5)
        ).isoformat()

        supabase_admin.table(
            'email_otps'
        ).upsert({
            "email": email,
            "otp_code": otp_code,
            "expires_at": expires_at,
            "is_used": False
        }).execute()

        msg = Message(
            'Kode OTP MIND DRIJI',
            recipients=[email]
        )

        msg.body = f'''
Halo,

Kode OTP verifikasi akun MIND DRIJI:

{otp_code}

OTP berlaku selama 5 menit.

Jangan berikan kode ini kepada siapapun.
'''

        mail.send(msg)

        return jsonify({
            "status": "success",
            "message": "OTP berhasil dikirim"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/forgot-password/send-otp', methods=['POST'])
def forgot_password_send_otp():
    try:
        data = request.get_json()

        email = data.get('email')

        if not email:
            return jsonify({
                "status": "error",
                "message": "Email wajib diisi"
            }), 400

        user = supabase_admin.table(
            'profiles'
        ).select('*').eq(
            'email', email
        ).execute()

        if not user.data:
            return jsonify({
                "status": "error",
                "message": "Email tidak terdaftar"
            }), 404

        otp_code = str(random.randint(100000, 999999))

        expires_at = (
            datetime.utcnow() +
            timedelta(minutes=5)
        ).isoformat()

        supabase_admin.table(
            'email_otps'
        ).upsert({
            "email": email,
            "otp_code": otp_code,
            "expires_at": expires_at,
            "is_used": False
        }).execute()

        msg = Message(
            'Reset Password MIND DRIJI',
            recipients=[email]
        )

        msg.body = f'''
Halo,

Kode OTP reset password MIND DRIJI:

{otp_code}

OTP berlaku selama 5 menit.
'''

        mail.send(msg)

        return jsonify({
            "status": "success",
            "message": "OTP berhasil dikirim"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/forgot-password/reset', methods=['POST'])
def reset_password():
    try:
        data = request.get_json()

        email = data.get('email')
        otp = data.get('otp')
        password_baru = data.get('password')

        result = supabase_admin.table(
            'email_otps'
        ).select('*').eq(
            'email', email
        ).execute()

        if not result.data:
            return jsonify({
                "status": "error",
                "message": "OTP tidak ditemukan"
            }), 404

        otp_data = result.data[0]

        if otp_data["is_used"]:
            return jsonify({
                "status": "error",
                "message": "OTP sudah digunakan"
            }), 400

        if otp_data["otp_code"] != otp:
            return jsonify({
                "status": "error",
                "message": "OTP salah"
            }), 400

        expires_at = datetime.fromisoformat(
            otp_data["expires_at"].replace(
                "Z", "+00:00"
            )
        )

        if datetime.utcnow() > expires_at.replace(tzinfo=None):
            return jsonify({
                "status": "error",
                "message": "OTP kadaluarsa"
            }), 400

        user_result = supabase_admin.table(
            'profiles'
        ).select('id').eq(
            'email', email
        ).single().execute()

        user_id = user_result.data['id']

        supabase_admin.auth.admin.update_user_by_id(
            user_id,
            {
                "password": password_baru
            }
        )

        supabase_admin.table(
            'email_otps'
        ).update({
            "is_used": True
        }).eq(
            'email', email
        ).execute()

        return jsonify({
            "status": "success",
            "message": "Password berhasil diubah"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# ➡️ 5. API UPDATE PROFIL (DARI MOBILE)
@app.route('/api/profile/update', methods=['PUT'])
def update_profile():
    try:
        data = request.get_json()
        email = data.get('email')
        nama_lengkap = data.get('nama_lengkap')
        no_hp = data.get('no_hp')
        jenis_kelamin = data.get('jenis_kelamin')
        tanggal_lahir = data.get('tanggal_lahir')
        password_konfirmasi = data.get('password_konfirmasi')

        if not email or not password_konfirmasi:
            return jsonify({"status": "error", "message": "Email dan password konfirmasi wajib diisi!"}), 400

        user_query = supabase.table('profiles').select('*').eq('email', email).execute()
        
        if not user_query.data:
            return jsonify({"status": "error", "message": "User tidak ditemukan!"}), 404

        user_data = user_query.data[0]

        if not check_password_hash(user_data['password'], password_konfirmasi):
            return jsonify({"status": "error", "message": "Konfirmasi password salah! Gagal memperbarui data."}), 401

        update_data = {
            "nama_lengkap": nama_lengkap,
            "no_hp": no_hp,
            "jenis_kelamin": jenis_kelamin,
            "tanggal_lahir": tanggal_lahir if tanggal_lahir != "" else None
        }

        update_query = supabase.table('profiles').update(update_data).eq('email', email).execute()

        if update_query.data:
            updated_user = update_query.data[0]
            if 'password' in updated_user:
                del updated_user['password']

            return jsonify({
                "status": "success",
                "message": "Profil berhasil diperbarui.",
                "user": updated_user
            }), 200
        else:
            return jsonify({"status": "error", "message": "Gagal mengupdate data ke database."}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan pada server: {str(e)}"}), 500


# ── INTERFACE API UNTUK CONSUME DATA LAIN ────────────────────
@app.route('/api/pengguna', methods=['GET'])
def api_pengguna():
    try:
        pengguna_list, db_error = get_all_pengguna()
        if db_error:
            return jsonify({"success": False, "message": db_error}), 500
        return jsonify({"success": True, "total": len(pengguna_list), "data": pengguna_list})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
# ── 🚀 API UNTUK MENGIRIM DAFTAR ARTIKEL KE FLUTTER ──
@app.route('/api/articles', methods=['GET'])
def get_all_articles():
    try:
        # Tarik semua artikel, urutkan dari yang paling baru (_id: -1)
        cursor = mongo_collection.find({}).sort('_id', -1)
        
        articles_list = []
        for doc in cursor:
            # PENTING: Ubah ObjectId MongoDB menjadi string biasa agar bisa di-render jadi JSON
            doc['_id'] = str(doc['_id'])
            articles_list.append(doc)
            
        return jsonify({
            "success": True,
            "total": len(articles_list),
            "data": articles_list
        }), 200
        
    except Exception as e:
        print(f"💥 Error ambil artikel: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

# ── 🟡 HELPER FUNCTION: Mengubah string "22 Jul 2022, 11:32 WIB" menjadi objek tanggal Python
def parse_mongo_date(date_str):
    if not date_str:
        return None
    try:
        # 1. Bersihkan teks: hapus WIB, hapus koma, jadikan huruf kecil semua
        clean_str = date_str.replace("WIB", "").replace(",", "").lower().strip()
        parts = clean_str.split() # Contoh hasil: ['22', 'jul', '2022', '11:32']
        
        if len(parts) < 4:
            return None
            
        day = parts[0]
        bulan_asal = parts[1]
        year = parts[2]
        time_str = parts[3]
        
        # 2. Kamus angka bulan (Mencakup variasi ketikan Indonesia & Inggris)
        month_map = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04", 
            "mei": "05", "may": "05", "jun": "06", "jul": "07", 
            "agu": "08", "agt": "08", "aug": "08", "sep": "09", 
            "okt": "10", "oct": "10", "nov": "11", "des": "12", "dec": "12"
        }
        
        month_num = month_map.get(bulan_asal)
        if not month_num:
            print(f"⚠️ Bulan tidak dikenali: {bulan_asal}")
            return None
            
        # 3. Satukan menjadi format angka murni: "22 07 2022 11:32"
        numeric_date_str = f"{day} {month_num} {year} {time_str}"
        
        # 4. Parse menggunakan format angka (%m) -> Bebas dari intervensi bahasa OS Laptop!
        return datetime.strptime(numeric_date_str, "%d %m %Y %H:%M")
        
    except Exception as e:
        print(f"❌ Gagal total parse tanggal: {date_str}, error: {e}")
        return None


# ── 🚀 INTERFACE API UNTUK GRAPH & WORDCLOUD (LIVE MONGODB) ──
@app.route('/api/chart-data', methods=['GET'])
@login_required # Hanya admin yang sudah login lewat Supabase yang bisa akses
def get_chart_data():
    start_date_str = request.args.get('start_date') # Format dari HTML: YYYY-MM-DD
    end_date_str = request.args.get('end_date')     # Format dari HTML: YYYY-MM-DD
    
    try:
        # 1. Tarik semua data mentah dari MongoDB terlebih dahulu
        cursor = mongo_collection.find({})
        filtered_articles = []
        
        # 2. Proses Saring/Filter Berdasarkan Tanggal di Sisi Python
        if start_date_str and end_date_str:
            start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            # Set jam ke 23:59:59 di hari terakhir agar artikel di tanggal akhir tetap terbaca
            end_dt = datetime.strptime(end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            
            for doc in cursor:
                mongo_date_str = doc.get("date") or doc.get("tanggal")
                doc_dt = parse_mongo_date(mongo_date_str)
                
                # Jika konversi sukses dan masuk ke dalam range filter admin
                if doc_dt and (start_dt <= doc_dt <= end_dt):
                    filtered_articles.append(doc)
            
            print(f"🔍 [FILTER AKTIF] Berhasil menemukan {len(filtered_articles)} artikel dari rentang {start_date_str} s/d {end_date_str}")
        else:
            # JIKA TANPA FILTER (Kondisi pertama kali Admin buka Dashboard)
            filtered_articles = list(cursor)
            print(f"🔍 [DEFAULT DASHBOARD] Menampilkan seluruh data: {len(filtered_articles)} artikel")
            
        # 3. Satukan semua teks konten artikel (field 'content') menjadi satu teks besar
        all_text = " ".join([str(a.get('content', '')) for a in filtered_articles]).lower()
        
        # Bersihkan tanda baca (titik, koma, seru, dll) agar murni kata bersih
        all_text = re.sub(r'[^\w\s]', '', all_text)
        words = all_text.split()
        
        # 4. Filter Stopwords (Kata sambung fungsional bahasa Indonesia agar tidak mengotori grafik)
        stopwords = {
            'yang', 'dan', 'di', 'dari', 'ke', 'ini', 'itu', 'with', 'dengan', 'atau', 'untuk', 
            'ada', 'adalah', 'bisa', 'bahwa', 'pada', 'juga', 'sudah', 'saya', 'kamu', 'dia',
            'mereka', 'kita', 'secara', 'dalam', 'bukan', 'tidak', 'tak', 'telah', 'bagi',
            'oleh', 'akan', 'namun', 'tapi', 'ia', 'seperti', 'lebih', 'hal', 'mengapa'
        }
        # Hanya ambil kata yang bukan kata sambung & panjangnya lebih dari 2 huruf
        filtered_words = [w for w in words if w not in stopwords and len(w) > 2]
        
        # 5. Hitung Frekuensi Kata menggunakan Counter
        word_counts = Counter(filtered_words)
        
        # Format 1: Untuk Top 10 Bar Chart (Chart.js)
        top_10 = word_counts.most_common(10)
        bar_labels = [w[0] for w in top_10]
        bar_values = [w[1] for w in top_10]
        
        # Format 2: Untuk WordCloud (AnyChart butuh format array of object [{'x': kata, 'value': jumlah}])
        top_50 = word_counts.most_common(50) # Ambil 50 kata biar WordCloud-nya ramai dan padat
        wordcloud_data = [{"x": w[0], "value": w[1]} for w in top_50]
        
        return jsonify({
            "success": True,
            "total_articles": len(filtered_articles),
            "bar_chart": {
                "labels": bar_labels,
                "values": bar_values
            },
            "wordcloud": wordcloud_data
        })
        
    except Exception as e:
        print(f"💥 Terjadi error pada API chart-data: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    

# ── ROUTES DASHBOARD PANEL WEB ADMIN (SERVE HTML) ────────────

@app.route('/')
@login_required
def dashboard():
    total_artikel = mongo_collection.count_documents({})
    return render_template(
        'dashboard.html',
        total_artikel=total_artikel,
        active_page='dashboard')

@app.route('/pengguna')
@login_required
def pengguna():
    search = request.args.get('q', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = 10

    pengguna_list, db_error = get_all_pengguna()

    # Logika Filter Struktur Berdasarkan Kata Kunci Pencarian
    if search:
        q = search.lower()
        pengguna_list = [
            u for u in pengguna_list
            if q in u['nama_lengkap'].lower()
            or q in u['email'].lower()
            or q in u['no_hp'].lower()
        ]

    all_pengguna, _ = get_all_pengguna()
    stats = {'total': len(all_pengguna)}

    # Implementasi Pembagian Halaman (Pagination)
    total = len(pengguna_list)
    total_pages = max(1, -(-total // per_page))
    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page
    pengguna_page = pengguna_list[start:end]

    return render_template(
        'pengguna.html',
        pengguna=pengguna_page,
        stats=stats,
        db_error=db_error,
        search=search,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
        active_page='pengguna',
    )

@app.route('/pengguna/<uid>/hapus', methods=['POST'])
@login_required
def hapus_pengguna(uid):
    try:
        supabase_admin.table('profiles').delete().eq('id', uid).execute()
        flash('Pengguna berhasil dihapus.', 'success')
    except Exception as e:
        flash(f'Gagal menghapus pengguna: {e}', 'danger')
    return redirect(url_for('pengguna'))

@app.route('/monitoring')
@login_required
def monitoring():
    return render_template('monitoring.html', active_page='monitoring')

@app.route('/insight')
@login_required
def insight():
    return render_template('insight.html', active_page='insight')

@app.route('/notifikasi')
@login_required
def notifikasi():
    unread = sum(1 for n in NOTIFIKASI if not n['dibaca'])
    return render_template('notifikasi.html', notifikasi=NOTIFIKASI, unread=unread, active_page='notifikasi')

@app.route('/artikel')
@login_required
def artikel_page():
    cursor = mongo_collection.find().sort('_id', -1)

    artikel_list = []
    for doc in cursor:
        artikel_list.append({
            'id': str(doc.get('_id')),
            'title': doc.get('title', 'Tanpa Judul'),
            'link': doc.get('link', '#'),
            'content': doc.get('content', ''),
            'date': doc.get('date', '-'),
            'category': doc.get('category', 'Umum'),
            'content_length': int(doc.get('content_length', 0)),
            'status': doc.get('status', 'Draft'),
        })

    # Statistik
    status_counter = Counter(a['status'] for a in artikel_list)
    kategori_counter = Counter(a['category'] for a in artikel_list)

    status_counts = dict(status_counter)
    kategori_counts = dict(kategori_counter)
    kategori_list = sorted(kategori_counter.keys())
    total_kategori = len(kategori_list)

    # Top 5 artikel berdasarkan panjang konten
    top_artikel = sorted(
        artikel_list,
        key=lambda a: a['content_length'],
        reverse=True
    )[:5]

    top_artikel = [
        {
            'title': a['title'],
            'content_length': a['content_length']
        }
        for a in top_artikel
    ]

    total_artikel = len(artikel_list)
    total_publikasi = (
        status_counter.get('Publikasi', 0)
        + status_counter.get('Published', 0)
    )
    total_draft = status_counter.get('Draft', 0)
    total_review = status_counter.get('Review', 0)
    total_karakter = sum(a['content_length'] for a in artikel_list)

    return render_template(
        'artikel.html',
        artikel=artikel_list,
        status_counts=status_counts,
        kategori_counts=kategori_counts,
        kategori_list=kategori_list,
        top_artikel=top_artikel,
        total_artikel=total_artikel,
        total_publikasi=total_publikasi,
        total_draft=total_draft,
        total_review=total_review,
        total_karakter=total_karakter,
        total_kategori=total_kategori,
        active_page='artikel'
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_email' in session:
        return redirect(url_for('dashboard'))
    error = None
    prefill_email = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        prefill_email = email
        if not email or not password:
            error = 'Email dan password wajib diisi.'
        else:
            result = do_supabase_login(email, password)
            if result['ok']:
                session.permanent = bool(remember)
                session['admin_email'] = result['email']
                session['admin_nama'] = result['nama']
                session['admin_role'] = result['role']
                session['admin_avatar'] = result['avatar']
                session['admin_uid'] = result['uid']
                flash(f"Selamat datang, {result['nama']}! 👋", 'success')
                return redirect(url_for('dashboard'))
            else:
                error = result['error']
    return render_template('login.html', error=error, prefill_email=prefill_email)

@app.route('/logout')
@login_required
def logout():
    nama = session.get('admin_nama', 'Admin')
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    session.clear()
    flash(f'Sampai jumpa, {nama}! Anda telah berhasil logout.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)