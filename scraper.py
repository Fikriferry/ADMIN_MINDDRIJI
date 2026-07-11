import os
import re
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pymongo import MongoClient, UpdateOne
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from playwright.sync_api import sync_playwright

# =====================================
# 1. DATA COLLECTION (AUTOMATED BROWSER)
# =====================================
print("Menjalankan scraping dengan Playwright...")
url = "https://www.idntimes.com/search?q=doomscrolling"
headers = {"User-Agent": "Mozilla/5.0"}
articles = []

with sync_playwright() as p:
    print("Membuka browser...")
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page.goto(url)

    jumlah_klik = 3

    for i in range(jumlah_klik):
        try:
            print(f"Mencoba memunculkan tombol Load More ke-{i+1}...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            tombol_load_more = page.wait_for_selector('button:has-text("Load More")', timeout=5000)

            if tombol_load_more:
                tombol_load_more.scroll_into_view_if_needed()
                time.sleep(1)
                tombol_load_more.click()
                print(f"-> 🚀 BERHASIL KLIK tombol Load More ke-{i+1}!")
                time.sleep(3)
            else:
                print("Tombol tidak ditemukan.")
                break
        except Exception:
            print("Tombol Load More sudah tidak terlihat/halaman sudah mentok habis.")
            break

    html_terakhir = page.content()
    browser.close()

soup = BeautifulSoup(html_terakhir, "lxml")
titles = soup.find_all("h3")

for t in titles:
    title = t.text.strip()
    parent = t.find_parent("a")
    if parent:
        link = parent.get("href")
        if link.startswith("/"):
            link = "https://www.idntimes.com" + link
        articles.append({"title": title, "link": link})

df = pd.DataFrame(articles)
df.drop_duplicates(subset=["link"], inplace=True)
print("Jumlah total artikel ditemukan (hasil scraping baru):", len(df))


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
    except Exception:
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
print("Jumlah artikel valid (hasil scraping baru):", len(df))

# =====================================
# 2. DATA PREPARATION (dijalankan sebelum simpan, supaya clean_content ikut ke-upsert)
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
# 3. DATA STORAGE (MongoDB) — UPSERT, TIDAK WIPE, ANTI-DUPLIKAT
# =====================================
print("Menghubungkan ke MongoDB...")
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI, tls=True)
db = client["mind_driji"]
collection = db["artikel_doomscrolling"]

# Pastikan field "link" unik di level database, jaring pengaman kedua
# selain logic upsert di bawah. create_index aman dipanggil berulang kali,
# tidak akan bikin index dobel kalau sudah ada.
collection.create_index("link", unique=True)

data = df.to_dict("records")

# Cek dulu link mana saja yang SUDAH ada di database sebelum upsert,
# supaya kita bisa tahu persis judul-judul mana yang benar-benar baru.
links_hasil_scraping = [row["link"] for row in data]
links_sudah_ada = set()
if links_hasil_scraping:
    existing_cursor = collection.find(
        {"link": {"$in": links_hasil_scraping}}, {"link": 1}
    )
    links_sudah_ada = {doc["link"] for doc in existing_cursor}

print("=" * 50)
print(f"Total artikel hasil scraping kali ini : {len(data)}")
print(f"Sudah ada di database sebelumnya       : {len(links_sudah_ada)}")
print(f"Berpotensi artikel baru                : {len(data) - len(links_sudah_ada)}")
print("=" * 50)

if data:
    operations = []
    judul_baru = []
    for row in data:
        row_copy = dict(row)
        link = row_copy.pop("link")

        if link not in links_sudah_ada:
            judul_baru.append(row_copy.get("title", link))

        operations.append(
            UpdateOne(
                {"link": link},
                {
                    # $set: field ini akan selalu diupdate tiap kali artikel yang sama
                    # ditemukan lagi (konten/tanggal/kategori bisa saja berubah/diperbaiki)
                    "$set": row_copy,
                    # $setOnInsert: field ini HANYA diisi saat dokumen benar-benar baru.
                    # Kalau artikel sudah ada, status hasil review admin di Flask
                    # (Review/Approved/Rejected, dll) TIDAK akan ketimpa ulang jadi "Review".
                    "$setOnInsert": {"link": link, "status": "Review"},
                },
                upsert=True,
            )
        )

    result = collection.bulk_write(operations, ordered=False)

    print("\n----- HASIL SCRAPING -----")
    if result.upserted_count > 0:
        print(f"✅ Ada {result.upserted_count} artikel BARU masuk ke database:")
        for judul in judul_baru:
            print(f"   - {judul}")
    else:
        print("ℹ️  Tidak ada artikel baru. Semua artikel hasil scraping kali ini "
              "sudah pernah tersimpan sebelumnya.")

    print(f"🔄 Artikel lama yang datanya diperbarui: {result.modified_count}")
    print(f"📦 Total dokumen di koleksi sekarang    : {collection.count_documents({})}")
    print("---------------------------\n")
else:
    print("Scraping kosong (tidak ada artikel ditemukan), tidak ada perubahan ke database.")

print("===== PROSES SELESAI =====")