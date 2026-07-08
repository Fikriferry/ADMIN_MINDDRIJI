import os
import re
import time
from collections import Counter
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pymongo import MongoClient
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import seaborn as sns
from playwright.sync_api import sync_playwright
# =====================================
# 1. DATA COLLECTION (AUTOMATED BROWSER)
# =====================================
print("Menjalankan scraping dengan Playwright...")
url = "https://www.idntimes.com/search?q=doomscrolling"
headers = {"User-Agent": "Mozilla/5.0"}
articles = []

# Menjalankan browser mini di latar belakang
with sync_playwright() as p:
    print("Membuka browser...")
    browser = p.chromium.launch(headless=True) # headless=True agar berjalan tanpa layar di GitHub
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page.goto(url)
    
    # 🟡 MAU KLIK "LOAD MORE" BERAPA KALI? 
    # Misal kita klik 3 kali untuk memunculkan +30 artikel tambahan
    jumlah_klik = 3 
    
    for i in range(jumlah_klik):
        try:
            print(f"Mengklik tombol Load More ke-{i+1}...")
            # Robot akan mencari tombol yang mengandung teks "Load More"
            tombol_load_more = page.locator("text=Load More").first
            
            if tombol_load_more.is_visible():
                tombol_load_more.click()
                time.sleep(3) # Tunggu 3 detik biar artikel baru selesai loading
            else:
                print("Tombol Load More sudah tidak terlihat, semua data mungkin sudah keluar.")
                break
        except Exception as e:
            print(f"Batal klik karena: {e}")
            break
            
    # Ambil seluruh isi HTML halaman setelah semua tombol di-klik
    html_terakhir = page.content()
    browser.close()

# Umpan HTML dari Playwright ke BeautifulSoup seperti biasa
soup = BeautifulSoup(html_terakhir, "lxml")
titles = soup.find_all("h3")

for t in titles:
    title = t.text.strip()
    parent = t.find_parent("a")
    if parent:
        link = parent.get("href")
        # Pastikan link-nya lengkap
        if link.startswith("/"):
            link = "https://www.idntimes.com" + link
        articles.append({"title": title, "link": link})

df = pd.DataFrame(articles)
# Hapus duplikat link jika ada
df.drop_duplicates(subset=["link"], inplace=True)
print("Jumlah total artikel ditemukan:", len(df))

# --- FUNGSI AMBIL DETAIL ARTIKEL (Tetap pakai requests biasa karena ini buka link satu-satu) ---
import requests # tetap butuh di sini
def get_article_detail(url):
    try:
        res = requests.get(url, headers=headers)
        sp = BeautifulSoup(res.text, "lxml")
        paragraphs = sp.find_all("p")
        content = " ".join([p.text.strip() for p in paragraphs])
        date = sp.find("time")
        date = date.text.strip() if date else ""
        category = url.split("/")[3]
        return content, date, category
    except:
        return "", "", ""

contents, dates, categories = [], [], []
for link in df["link"]:
    content, date, category = get_article_detail(link)
    contents.append(content)
    dates.append(date)
    categories.append(category)
    time.sleep(1)

df["content"] = contents
df["date"] = dates
df["category"] = categories
df["content_length"] = df["content"].apply(len)
df = df[df["content_length"] > 100]
df.reset_index(drop=True, inplace=True)
print("Jumlah artikel valid:", len(df))

# =====================================
# 2. DATA STORAGE (MongoDB)
# =====================================
print("Menghubungkan ke MongoDB...")
MONGO_URI = os.environ.get("MONGO_URI") 
client = MongoClient(MONGO_URI, tls=True)
db = client["mind_driji"]
collection = db["artikel_doomscrolling"]

# 🟡 SUNTIKKAN STATUS DEFAULT UNTUK WEB ADMIN FLASK
df["status"] = "Review" 

data = df.to_dict("records")
if data:
    # 🟡 BERSIHKAN DATA LAMA (Wipe & Replace)
    print("Membersihkan data lama di database agar tidak menumpuk...")
    collection.delete_many({}) 
    
    # Masukkan data baru yang fresh
    collection.insert_many(data)
    print("Data terbaru berhasil diperbarui ke MongoDB.")
else:
    print("Scraping kosong, data lama tidak dihapus demi keamanan.")

# =====================================
# 3. DATA PREPARATION
# =====================================
print("Melakukan pre-processing data...")
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk.download('stopwords', quiet=True)

stop_words = set(stopwords.words('indonesian'))

def clean_text(text):
    text = str(text).lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[^a-zA-Z\s]", "", text)
    words = word_tokenize(text)
    words = [word for word in words if word not in stop_words]
    return " ".join(words)

df["clean_content"] = df["content"].apply(clean_text)
df["clean_title"] = df["title"].apply(clean_text)
df.dropna(inplace=True)
df = df[df["clean_content"] != ""]
df.reset_index(drop=True, inplace=True)

# =====================================
# 4. ANALYSIS & VISUALIZATION
# =====================================
print("Membuat visualisasi...")
all_text = " ".join(df["clean_content"])

# Wordcloud
wordcloud = WordCloud(width=1200, height=600, background_color='white').generate(all_text)
plt.figure(figsize=(15,6))
plt.imshow(wordcloud)
plt.axis("off")
plt.title("WordCloud Artikel Doomscrolling")
plt.savefig("wordcloud.png") 
plt.close()

# Top 10 Words
words = all_text.split()
word_counts = Counter(words)
top_words = word_counts.most_common(10)
top_df = pd.DataFrame(top_words, columns=["word", "count"])

plt.figure(figsize=(10,5))
sns.barplot(x="count", y="word", data=top_df)
plt.title("Top 10 Kata yang Sering Muncul")
plt.savefig("top_words.png") 
plt.close()

print("===== PROSES SELESAI =====")