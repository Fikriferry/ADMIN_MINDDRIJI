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

# =====================================
# 1. DATA COLLECTION
# =====================================
print("Menjalankan scraping...")
url = "https://www.idntimes.com/search?q=doomscrolling"
headers = {"User-Agent": "Mozilla/5.0"}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, "lxml")
articles = []

titles = soup.find_all("h3")
for t in titles:
    title = t.text.strip()
    parent = t.find_parent("a")
    if parent:
        link = parent.get("href")
        articles.append({"title": title, "link": link})

df = pd.DataFrame(articles)
print("Jumlah artikel ditemukan:", len(df))

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
# 🟡 AMBIL DARI GITHUB SECRETS (Jangan di-hardcode rawan hack!)
MONGO_URI = os.environ.get("MONGO_URI") 
client = MongoClient(MONGO_URI, tls=True)
db = client["mind_driji"]
collection = db["artikel_doomscrolling"]

data = df.to_dict("records")
if data:
    collection.insert_many(data)
print("Data berhasil disimpan ke MongoDB.")

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
plt.savefig("wordcloud.png") # 🟡 Diubah jadi SAVE biar ga macet di server
plt.close()

# Top 10 Words
words = all_text.split()
word_counts = Counter(words)
top_words = word_counts.most_common(10)
top_df = pd.DataFrame(top_words, columns=["word", "count"])

plt.figure(figsize=(10,5))
sns.barplot(x="count", y="word", data=top_df)
plt.title("Top 10 Kata yang Sering Muncul")
plt.savefig("top_words.png") # 🟡 Simpan gambar
plt.close()

print("===== PROSES SELESAI =====")