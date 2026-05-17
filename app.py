import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_cors import CORS
from functools import wraps
from dotenv import load_dotenv
import uuid  # Pastikan ini sudah diimport di bagian paling atas app.py
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback-secret-key')

# ── Supabase clients ─────────────────────────────────────────
# Client biasa (anon key) — untuk auth admin
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Client service role — untuk baca/tulis data pengguna (bypass RLS)
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY', SUPABASE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── Data dummy (notifikasi & artikel) ────────────────────────
NOTIFIKASI = [
    {"id": 1, "judul": "Pengguna baru terdaftar",      "isi": "Fajar Rahman baru saja mendaftar.",             "waktu": "2 menit lalu",   "tipe": "info",    "dibaca": False},
    {"id": 2, "judul": "AI Insight selesai diproses",  "isi": "Laporan insight untuk 45 pengguna selesai.",    "waktu": "15 menit lalu",  "tipe": "success", "dibaca": False},
    {"id": 3, "judul": "Peringatan penggunaan sistem", "isi": "Memori server mencapai 78%.",                    "waktu": "1 jam lalu",     "tipe": "warning", "dibaca": False},
    {"id": 4, "judul": "Artikel baru dipublikasi",     "isi": "Artikel 'Stres di Era Digital' dipublikasi.",   "waktu": "3 jam lalu",     "tipe": "info",    "dibaca": True},
    {"id": 5, "judul": "Pembaruan keamanan berhasil",  "isi": "Patch v2.3.1 berhasil diterapkan.",             "waktu": "Kemarin, 22:04", "tipe": "success", "dibaca": True},
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


# ════════════════════════════════════════
#  AUTH HELPERS
# ════════════════════════════════════════

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
    
    

# ➡️ 1. API REGISTRASI (MENG-HASH PASSWORD SEBELUM MASUK DATABASE)
@app.route('/api/register', methods=['POST'])
def register_user():
    try:
        data = request.get_json()
        
        email = data.get('email')
        password_polos = data.get('password')  # Input password biasa dari HP
        nama_lengkap = data.get('nama_lengkap')
        no_hp = data.get('no_hp', '')
        jenis_kelamin = data.get('jenis_kelamin', 'Laki-laki')
        tanggal_lahir = data.get('tanggal_lahir')

        if not email or not password_polos:
            return jsonify({"status": "error", "message": "Email dan password wajib diisi!"}), 400

        # Proses Hashing: Mengubah password biasa menjadi kode acak panjang untuk di DB
        password_ter_hash = generate_password_hash(password_polos)
        user_id = str(uuid.uuid4())

        # Masukkan data ke tabel 'profiles'
        supabase.table('profiles').insert({
            'id': user_id,
            'nama_lengkap': nama_lengkap,
            'email': email,
            'password': password_ter_hash,  # Menyimpan versi hash acak yang aman
            'no_hp': no_hp,
            'tanggal_lahir': tanggal_lahir if (tanggal_lahir and tanggal_lahir != '-') else None,
            'jenis_kelamin': jenis_kelamin
        }).execute()

        return jsonify({"status": "success", "message": "Akun dan profil berhasil dibuat!"}), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ➡️ 2. API LOGIN (MENCOCOKKAN INPUT BIASA VS HASH DI DATABASE)
@app.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        email = data.get('email')
        password_input = data.get('password') # Input password biasa dari HP

        if not email or not password_input:
            return jsonify({"status": "error", "message": "Email dan password wajib diisi!"}), 400

        # Ambil semua data profil dari tabel 'profiles'
        user_query = supabase.table('profiles').select('*').eq('email', email).execute()

        if not user_query.data:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        user_data = user_query.data[0]

        # Verifikasi: Apakah password biasa cocok dengan kode hash di DB?
        if not check_password_hash(user_data['password'], password_input):
            return jsonify({"status": "error", "message": "Password yang Anda masukkan salah!"}), 401

        # Hapus password dari response demi keamanan data internet
        if 'password' in user_data:
            del user_data['password']

        return jsonify({
            "status": "success",
            "message": "Login berhasil",
            "user": user_data  # Membawa data lengkap (no_hp, jenis_kelamin, tanggal_lahir)
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
# ➡️ 3. API UPDATE PROFIL (KONFIRMASI PASSWORD BIASA VS HASH DI DATABASE)
@app.route('/api/profile/update', methods=['PUT'])
def update_profile():
    try:
        data = request.get_json()
        
        email = data.get('email')
        nama_lengkap = data.get('nama_lengkap')
        no_hp = data.get('no_hp')
        jenis_kelamin = data.get('jenis_kelamin')
        tanggal_lahir = data.get('tanggal_lahir') 
        password_konfirmasi = data.get('password_konfirmasi') # Input password biasa dari HP

        if not email or not password_konfirmasi:
            return jsonify({"status": "error", "message": "Email dan password konfirmasi wajib diisi!"}), 400

        # Cari user saat ini di tabel 'profiles'
        user_query = supabase.table('profiles').select('*').eq('email', email).execute()
        
        if not user_query.data:
            return jsonify({"status": "error", "message": "User tidak ditemukan!"}), 404

        user_data = user_query.data[0]

        # Cocokkan password konfirmasi biasa dengan hash di DB
        if not check_password_hash(user_data['password'], password_konfirmasi):
            return jsonify({"status": "error", "message": "Konfirmasi password salah! Gagal memperbarui data."}), 401

        # Jika lolos verifikasi, jalankan update ke tabel 'profiles'
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


# ════════════════════════════════════════
#  PENGGUNA HELPERS
# ════════════════════════════════════════

def get_pengguna_stats(semua):
    return {'total': len(semua)}


def format_tanggal(iso_str):
    """Ubah '1995-03-15' atau ISO datetime → '15 Mar 1995'."""
    if not iso_str:
        return '-'
    try:
        from datetime import datetime
        bulan = ['','Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des']
        # Potong bagian waktu jika ada
        tgl = iso_str[:10]
        y, m, d = tgl.split('-')
        return f"{int(d)} {bulan[int(m)]} {y}"
    except Exception:
        return iso_str


def hitung_usia(tanggal_lahir_str):
    """Hitung usia dari string tanggal lahir."""
    if not tanggal_lahir_str:
        return '-'
    try:
        from datetime import date
        tgl = tanggal_lahir_str[:10]
        y, m, d = map(int, tgl.split('-'))
        lahir = date(y, m, d)
        hari_ini = date.today()
        usia = hari_ini.year - lahir.year - ((hari_ini.month, hari_ini.day) < (lahir.month, lahir.day))
        return f"{usia} thn"
    except Exception:
        return '-'


def get_all_pengguna():
    """
    Ambil semua pengguna dari tabel profiles di Supabase.
    Menggunakan supabase_admin (service role) agar bisa bypass RLS.
    Return: (list_pengguna, error_message)
    """
    try:
        resp = (
            supabase_admin
            .table('profiles')
            .select('id, nama_lengkap, email, no_hp, tanggal_lahir, jenis_kelamin, avatar_url, created_at')
            .order('created_at', desc=True)
            .execute()
        )
        rows = resp.data or []

        # Format data untuk template
        pengguna = []
        for i, row in enumerate(rows):
            nama = row.get('nama_lengkap') or row.get('email', '').split('@')[0].title()
            pengguna.append({
                'no':             i + 1,
                'id':             row.get('id', ''),
                'nama':           nama,
                'email':          row.get('email', '-'),
                'no_hp':          row.get('no_hp') or '-',
                'tanggal_lahir':  format_tanggal(row.get('tanggal_lahir')),
                'jenis_kelamin':  row.get('jenis_kelamin') or '-',
                'avatar_url':     row.get('avatar_url'),
                'avatar_letter':  nama[0].upper() if nama else '?',
                'bergabung':      format_tanggal(row.get('created_at')),
                'usia':           hitung_usia(row.get('tanggal_lahir')),
            })
        return pengguna, None

    except Exception as e:
        return [], f"Gagal memuat data pengguna: {str(e)[:120]}"


# ════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_email' in session:
        return redirect(url_for('dashboard'))
    error = None
    prefill_email = ''
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        prefill_email = email
        if not email or not password:
            error = 'Email dan password wajib diisi.'
        else:
            result = do_supabase_login(email, password)
            if result['ok']:
                session.permanent = bool(remember)
                session['admin_email']  = result['email']
                session['admin_nama']   = result['nama']
                session['admin_role']   = result['role']
                session['admin_avatar'] = result['avatar']
                session['admin_uid']    = result['uid']
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


# ════════════════════════════════════════
#  PROTECTED ROUTES
# ════════════════════════════════════════

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', active_page='dashboard')


@app.route('/pengguna')
@login_required
def pengguna():
    # Ambil filter & search dari query string
    search  = request.args.get('q', '').strip()
    page    = max(1, int(request.args.get('page', 1)))
    per_page = 10

    pengguna_list, db_error = get_all_pengguna()

    # Filter pencarian
    if search:
        q = search.lower()
        pengguna_list = [
            u for u in pengguna_list
            if q in u['nama'].lower()
            or q in u['email'].lower()
            or q in u['no_hp'].lower()
        ]


    # Statistik (dari data asli sebelum filter)
    all_pengguna, _ = get_all_pengguna()
    stats = get_pengguna_stats(all_pengguna)

    # Pagination
    total        = len(pengguna_list)
    total_pages  = max(1, -(-total // per_page))   # ceiling division
    page         = min(page, total_pages)
    start        = (page - 1) * per_page
    end          = start + per_page
    pengguna_page = pengguna_list[start:end]

    return render_template(
        'pengguna.html',
        pengguna       = pengguna_page,
        stats          = stats,
        db_error       = db_error,
        search         = search,
        page           = page,
        total_pages    = total_pages,
        total          = total,
        per_page       = per_page,
        active_page    = 'pengguna',
    )

@app.route('/api/pengguna', methods=['GET'])
def api_pengguna():

    try:

        pengguna_list, db_error = get_all_pengguna()

        if db_error:
            return jsonify({
                "success": False,
                "message": db_error
            }), 500

        return jsonify({
            "success": True,
            "total": len(pengguna_list),
            "data": pengguna_list
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@app.route('/pengguna/<uid>/hapus', methods=['POST'])
@login_required
def hapus_pengguna(uid):
    """Hapus pengguna dari tabel profiles."""
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
    return render_template('notifikasi.html', notifikasi=NOTIFIKASI,
                           unread=unread, active_page='notifikasi')


@app.route('/artikel')
@login_required
def artikel():
    return render_template('artikel.html', artikel=ARTIKEL, active_page='artikel')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)