import cloudscraper
import re
import json
import os
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import base64
import hashlib

# --- GEREKLİ YARDIMCI FONKSİYONLAR ---

def sanitize_filename(filename):
    """Dosya adlarında geçersiz olan karakterleri temizler."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def __md5(data):
    return hashlib.md5(data).digest()

def decrypt_cizgiduo(encrypted_data, password):
    """Kotlin kodundaki AesHelper.cryptoAESHandler fonksiyonunu taklit eder."""
    try:
        encrypted_bytes = base64.b64decode(encrypted_data)
        salt = encrypted_bytes[8:16]
        key_iv = b''
        temp = b''
        while len(key_iv) < 48:
            temp = __md5(temp + password.encode() + salt)
            key_iv += temp
        key = key_iv[:32]
        iv = key_iv[32:48]
        cipher_text = encrypted_bytes[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted_padded = cipher.decrypt(cipher_text)
        decrypted = unpad(decrypted_padded, AES.block_size)
        return decrypted.decode('utf-8')
    except Exception:
        # Hata durumunda None döndürerek programın çökmesini engelle
        return None

# --- EXTRACTOR'LAR ---

def extract_cizgiduo(scraper, iframe_url):
    """CizgiDuo/CizgiPass iframe'inden M3U8 linkini çeker."""
    try:
        res = scraper.get(iframe_url, timeout=15)
        res.raise_for_status()
        match = re.search(r"bePlayer\('([^']*)',\s*'([^']*)'\);", res.text)
        if not match: return None

        password, encrypted_json_str = match.group(1), match.group(2)
        player_data = json.loads(encrypted_json_str)
        encrypted_source_data = player_data.get("sources")[0].get("file")
        
        decrypted_str = decrypt_cizgiduo(encrypted_source_data, password)
        if not decrypted_str: return None

        m3u_match = re.search(r'"file":"([^"]+)"', decrypted_str)
        if m3u_match:
            m3u_link = m3u_match.group(1).replace('\\/', '/')
            return {"name": "CizgiDuo", "url": m3u_link, "referer": iframe_url}
        return None
    except Exception as e:
        print(f"  [!] CizgiDuo Hata: {e}")
        return None

def extract_sibnet(scraper, iframe_url):
    """SibNet iframe'inden video linkini çeker."""
    try:
        res = scraper.get(iframe_url, timeout=15)
        res.raise_for_status()
        match = re.search(r'player\.src\(\[\{src: "([^"]+)"', res.text)
        if match:
            video_path = match.group(1)
            video_url = urljoin("https://video.sibnet.ru", video_path)
            return {"name": "SibNet", "url": video_url, "referer": iframe_url}
        return None
    except Exception as e:
        print(f"  [!] SibNet Hata: {e}")
        return None

# --- ANA SCRAPER SINIFI ---

class CizgiMaxFullScraper:
    def __init__(self):
        self.base_url = "https://cizgimax.online"
        self.scraper = cloudscraper.create_scraper()
        # Kotlin kodundaki ana sayfa kategorileri
        self.categories = {
            "Son Eklenenler": "/diziler/page/{page}?orderby=date&order=DESC",
            "Aile": "/diziler/page/{page}?s_type&tur[0]=aile&orderby=date&order=DESC",
            "Aksiyon": "/diziler/page/{page}?s_type&tur[0]=aksiyon-macera&orderby=date&order=DESC",
            "Animasyon": "/diziler/page/{page}?s_type&tur[0]=animasyon&orderby=date&order=DESC",
            "Bilim Kurgu": "/diziler/page/{page}?s_type&tur[0]=bilim-kurgu-fantazi&orderby=date&order=DESC",
        }
        self.output_dir = "m3u_playlists"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def get_series_from_page(self, page_url):
        """Belirtilen sayfadaki tüm serilerin adını ve linkini alır."""
        try:
            res = self.scraper.get(page_url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'lxml')
            series_list = []
            # Kotlin kodundaki gibi `ul.filter-results li` seçicisini kullanıyoruz.
            for item in soup.select("ul.filter-results li"):
                title_tag = item.select_first("h2.truncate")
                link_tag = item.select_first("div.poster-subject a")
                if title_tag and link_tag:
                    series_list.append({
                        "title": title_tag.text.strip(),
                        "url": link_tag.get("href")
                    })
            return series_list
        except Exception as e:
            print(f" [!] Seri listesi alınırken hata: {page_url} - {e}")
            return []

    def get_episodes(self, show_url):
        """Bir serinin tüm bölümlerini alır."""
        try:
            res = self.scraper.get(show_url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'lxml')
            episodes = [
                {"name": el.find('span', class_='episode-names').text.strip(), "url": el.find('a')['href']}
                for el in soup.select("div.asisotope div.ajax_post") if el.find('a') and el.find('span', class_='episode-names')
            ]
            return list(reversed(episodes))
        except Exception as e:
            print(f"   [!] Bölümler alınamadı: {show_url} - {e}")
            return []

    def get_video_sources(self, episode_url):
        """Bir bölümün tüm video kaynaklarını (iframe'leri) bulur."""
        sources = []
        try:
            res = self.scraper.get(episode_url, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'lxml')
            for link in soup.select("ul.linkler li a"):
                iframe_url = link.get('data-frame')
                if not iframe_url: continue
                
                source_info = None
                if 'cizgiduo' in iframe_url or 'cizgipass' in iframe_url:
                    source_info = extract_cizgiduo(self.scraper, iframe_url)
                elif 'sibnet' in iframe_url:
                    source_info = extract_sibnet(self.scraper, iframe_url)
                
                if source_info:
                    sources.append(source_info)
            return sources
        except Exception as e:
            print(f"     [!] Video kaynağı alınamadı: {episode_url} - {e}")
            return []

    def run(self):
        """Ana tarama işlemini başlatır."""
        processed_series_urls = set()

        for category_name, category_path in self.categories.items():
            print(f"\n--- Kategori Taranıyor: {category_name} ---")
            page = 1
            while True:
                page_url = f"{self.base_url}{category_path.format(page=page)}"
                print(f"\n -> Sayfa {page} taranıyor: {page_url}")
                
                series_on_page = self.get_series_from_page(page_url)
                if not series_on_page:
                    print(f" -> Sayfa {page} boş, kategori tamamlandı.")
                    break

                for series in series_on_page:
                    if series["url"] in processed_series_urls:
                        print(f" - '{series['title']}' daha önce işlendi, atlanıyor.")
                        continue
                    
                    print(f"  -> Seri işleniyor: {series['title']}")
                    processed_series_urls.add(series["url"])

                    episodes = self.get_episodes(series["url"])
                    if not episodes:
                        print(f"   [!] '{series['title']}' için bölüm bulunamadı.")
                        continue
                    
                    print(f"   -> {len(episodes)} bölüm bulundu.")
                    
                    all_sources_for_series = []
                    for episode in episodes:
                        print(f"    -> Bölüm taranıyor: {episode['name']}")
                        # IP ban yememek için küçük bir bekleme
                        time.sleep(1) 
                        video_sources = self.get_video_sources(episode["url"])
                        if video_sources:
                            # M3U formatına bölüm adını da ekliyoruz
                            for source in video_sources:
                                source['name'] = f"{episode['name']} - {source['name']}"
                            all_sources_for_series.extend(video_sources)

                    if all_sources_for_series:
                        filename = sanitize_filename(f"{series['title']}.m3u")
                        filepath = os.path.join(self.output_dir, filename)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write("#EXTM3U\n")
                            for item in all_sources_for_series:
                                f.write(f"#EXTINF:-1 tvg-name=\"{item['name']}\" group-title=\"{series['title']}\",{item['name']}\n")
                                f.write(f"#EXTVLCOPT:http-referrer={item['referer']}\n")
                                f.write(f"{item['url']}\n")
                        print(f"   [+] M3U dosyası oluşturuldu: {filepath}")
                
                page += 1
                time.sleep(2) # Sayfalar arası bekleme

if __name__ == "__main__":
    scraper = CizgiMaxFullScraper()
    scraper.run()
    print("\nTarama işlemi tamamlandı.")