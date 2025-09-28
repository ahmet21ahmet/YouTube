import cloudscraper
import re
import json
import argparse
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import base64
import hashlib

# --- ŞİFRE ÇÖZME VE YARDIMCI FONKSİYONLAR ---

def __md5(data):
    """MD5 hash fonksiyonu, key türetme için kullanılır."""
    return hashlib.md5(data).digest()

def decrypt_cizgiduo(encrypted_data, password):
    """Kotlin kodundaki AesHelper.cryptoAESHandler fonksiyonunu taklit eder."""
    try:
        encrypted_bytes = base64.b64decode(encrypted_data)
        salt = encrypted_bytes[8:16]
        key_iv = bytes()
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
    except Exception as e:
        print(f"  [!] CizgiDuo şifre çözme hatası: {e}")
        return None

# --- EXTRACTOR FONKSİYONLARI ---

def extract_cizgiduo(scraper, iframe_url):
    """CizgiDuo/CizgiPass iframe'inden M3U8 linkini çeker."""
    print(f"  [*] CizgiDuo extractor çalıştırılıyor: {iframe_url}")
    try:
        res = scraper.get(iframe_url)
        res.raise_for_status()
        match = re.search(r"bePlayer\('([^']*)',\s*'([^']*)'\);", res.text)
        if not match:
            print("  [!] CizgiDuo: bePlayer verisi bulunamadı.")
            return None

        password, encrypted_json_str = match.group(1), match.group(2)
        player_data = json.loads(encrypted_json_str)
        encrypted_source_data = player_data.get("sources")[0].get("file")
        
        decrypted_str = decrypt_cizgiduo(encrypted_source_data, password)
        if not decrypted_str:
            return None

        m3u_match = re.search(r'"file":"([^"]+)"', decrypted_str)
        if m3u_match:
            m3u_link = m3u_match.group(1).replace('\\/', '/')
            print(f"  [+] CizgiDuo: M3U8 linki bulundu!")
            return {"name": "CizgiDuo", "url": m3u_link, "referer": iframe_url}
        
        print("  [!] CizgiDuo: Çözülmüş veri içinde M3U8 linki bulunamadı.")
        return None
    except Exception as e:
        print(f"  [!] CizgiDuo extractor hatası: {e}")
        return None

def extract_sibnet(scraper, iframe_url):
    """SibNet iframe'inden video linkini çeker."""
    print(f"  [*] SibNet extractor çalıştırılıyor: {iframe_url}")
    try:
        res = scraper.get(iframe_url)
        res.raise_for_status()
        match = re.search(r'player\.src\(\[\{src: "([^"]+)"', res.text)
        if match:
            video_path = match.group(1)
            video_url = urljoin("https://video.sibnet.ru", video_path)
            print(f"  [+] SibNet: Video linki bulundu!")
            return {"name": "SibNet", "url": video_url, "referer": iframe_url}
        print(f"  [!] SibNet: Video linki bulunamadı.")
        return None
    except Exception as e:
        print(f"  [!] SibNet extractor hatası: {e}")
        return None

# --- ANA SCRAPER SINIFI ---

class CizgiMaxScraper:
    def __init__(self):
        self.base_url = "https://cizgimax.online"
        self.scraper = cloudscraper.create_scraper()
        print("CizgiMax Scraper başlatıldı.")

    def search(self, query):
        """AJAX servisini kullanarak arama yapar."""
        search_url = f"{self.base_url}/ajaxservice/index.php"
        print(f"\n'{query}' için arama yapılıyor...")
        res = self.scraper.get(search_url, params={'qr': query})
        res.raise_for_status()
        results = res.json().get('data', {}).get('result', [])
        return [
            {"title": item['s_name'], "url": item['s_link']}
            for item in results if ".Bölüm" not in item['s_name']
        ]

    def get_episodes(self, show_url):
        """Bir çizgi filmin sayfasına giderek bölümleri listeler."""
        print(f"\nBölümler alınıyor: {show_url}")
        res = self.scraper.get(show_url)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'lxml')
        episode_elements = soup.select("div.asisotope div.ajax_post")
        episodes = [
            {"name": el.find('span', class_='episode-names').text.strip(), "url": el.find('a')['href']}
            for el in episode_elements if el.find('a') and el.find('span', class_='episode-names')
        ]
        return list(reversed(episodes))

    def get_video_sources(self, episode_url):
        """Bölüm sayfasındaki video kaynaklarını (iframe'leri) bulur."""
        print(f"\nVideo kaynakları aranıyor: {episode_url}")
        res = self.scraper.get(episode_url)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'lxml')
        sources = []
        for link in soup.select("ul.linkler li a"):
            iframe_url = link.get('data-frame')
            if not iframe_url: continue
            
            print(f"\n-> Kaynak bulundu: {iframe_url}")
            source_info = None
            if 'cizgiduo' in iframe_url or 'cizgipass' in iframe_url:
                source_info = extract_cizgiduo(self.scraper, iframe_url)
            elif 'sibnet' in iframe_url:
                source_info = extract_sibnet(self.scraper, iframe_url)
            else:
                print(f"  [!] Desteklenmeyen kaynak: {iframe_url}")
            
            if source_info:
                sources.append(source_info)
        return sources

def create_m3u_file(playlist_data, filename="playlist.m3u"):
    """Verilen bilgilerle M3U formatında bir dosya oluşturur."""
    if not playlist_data:
        print("\nOluşturulacak M3U verisi bulunamadı.")
        return
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for item in playlist_data:
            f.write(f"#EXTINF:-1 tvg-name=\"{item['name']}\" group-title=\"CizgiMax\",{item['name']}\n")
            f.write(f"#EXTVLCOPT:http-referrer={item['referer']}\n")
            f.write(f"{item['url']}\n")
    print(f"\nBaşarılı! '{filename}' dosyası oluşturuldu.")

def main():
    parser = argparse.ArgumentParser(description="CizgiMax'ten veri çekip M3U listesi oluşturan otomasyon botu.")
    parser.add_argument("--query", required=True, help="Aramak istediğiniz çizgi filmin adı.")
    parser.add_argument("--series-choice", type=int, default=1, help="Arama sonuçlarından kaçıncı serinin seçileceği (varsayılan: 1).")
    parser.add_argument("--episode-choice", type=str, default="latest", help="Hangi bölümün seçileceği ('latest' veya bölüm numarası, varsayılan: 'latest').")
    args = parser.parse_args()

    scraper = CizgiMaxScraper()
    
    # 1. Arama yap
    search_results = scraper.search(args.query)
    if not search_results:
        print("Arama sonucu bulunamadı.")
        return

    # 2. Seriyi seç
    series_index = args.series_choice - 1
    if not (0 <= series_index < len(search_results)):
        print(f"Seri seçimi geçersiz. {len(search_results)} sonuç bulundu ama {args.series_choice}. sırayı istediniz.")
        return
    selected_show = search_results[series_index]
    print(f"\nSeri seçildi: '{selected_show['title']}'")

    # 3. Bölümleri al
    episodes = scraper.get_episodes(selected_show['url'])
    if not episodes:
        print("Hiç bölüm bulunamadı.")
        return

    # 4. Bölümü seç
    selected_episode = None
    if args.episode_choice.lower() == 'latest':
        selected_episode = episodes[-1]
    else:
        try:
            episode_index = int(args.episode_choice) - 1
            if 0 <= episode_index < len(episodes):
                selected_episode = episodes[episode_index]
            else:
                print(f"Bölüm seçimi geçersiz. {len(episodes)} bölüm var ama siz {args.episode_choice}. bölümü istediniz.")
                return
        except ValueError:
            print(f"Bölüm seçimi geçersiz: '{args.episode_choice}'. Lütfen 'latest' veya bir sayı girin.")
            return

    print(f"\nBölüm seçildi: '{selected_episode['name']}'")

    # 5. Video kaynaklarını bul ve M3U dosyası oluştur
    video_sources = scraper.get_video_sources(selected_episode['url'])
    create_m3u_file(video_sources)

if __name__ == "__main__":
    main()