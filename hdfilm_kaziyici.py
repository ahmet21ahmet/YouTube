from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By 
from bs4 import BeautifulSoup
import time
import re
import json

# --- YAPILANDIRMA ---
TARGET_URL = "https://www.hdfilmizle.to/"
# JavaScript'in çalışması ve sayfanın tamamen yüklenmesi için 
# örtülü bekleme süresini (implicit wait) kullanacağız.

def setup_driver():
    """Selenium WebDriver'ı headless modda başlatır."""
    try:
        chrome_options = Options()
        # Headless mod (Görünmez arkaplan)
        chrome_options.add_argument("--headless")
        # Güvenlik ve ortam uyumluluğu için gerekli ayarlar
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # Bot algılanmasını zorlaştırmak için User-Agent
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        # WebDriver başlatılıyor
        driver = webdriver.Chrome(options=chrome_options) 
        # Sayfa yüklenmesini makul bir süre bekler
        driver.set_page_load_timeout(30)
        # Öğeler bulunana kadar maksimum 10 saniye bekler (Örtülü Bekleme)
        driver.implicitly_wait(10)
        return driver
    except Exception as e:
        print(f"HATA: WebDriver başlatılamadı. Kurulumunuzu kontrol edin. Hata: {e}")
        return None

def find_player_links(driver, detail_url):
    """Film detay sayfasından video (.m3u8) ve altyazı linklerini bulmaya çalışır."""
    video_link = None
    subtitle_link = None
    
    # print(f"  -> Detay Sayfası Yükleniyor: {detail_url}")
    
    try:
        driver.get(detail_url)
        
        # Oynatıcıyı içeren IFRAME'i spesifik olarak bulmaya çalış (class="vpx" kullanılarak)
        iframe_element = None
        try:
            # iframe.vpx seçicisi ile IFRAME'i bul
            iframe_element = driver.find_element(By.CSS_SELECTOR, 'iframe.vpx')
        except:
            # Bulamazsa, tüm iframe'ler arasında ara (yedek)
            iframe_elements = driver.find_elements(By.TAG_NAME, 'iframe')
            iframe_element = iframe_elements[0] if iframe_elements else None

        
        if iframe_element:
            # IFRAME src adresini çekiyoruz (örn: https://vidrame.pro/vr/...)
            iframe_src = iframe_element.get_attribute('src')
            if iframe_src:
                # print(f"  -> IFRAME Kaynağı Bulundu: {iframe_src}")
                
                # Sürücüyü iframe'in kaynağına yönlendir (2. Aşama Kazıma)
                driver.get(iframe_src)
                
                # Yeni sayfadaki (iframe içeriği) kaynak kodu al
                iframe_html = driver.page_source
                
                # 1. Video Linkini Bulma (.m3u8 veya .mpd)
                # Oynatıcı kodunda video linkini regex ile arıyoruz
                m3u8_match = re.search(r'["\'](https?://[^"\']*\.m3u8|https?://[^"\']*\.mpd)["\']', iframe_html)
                if m3u8_match:
                    video_link = m3u8_match.group(1)
                
                # 2. Altyazı Linkini Bulma (.vtt veya .srt)
                vtt_match = re.search(r'["\'](https?://[^"\']*\.vtt|https?://[^"\']*\.srt)["\']', iframe_html)
                if vtt_match:
                    subtitle_link = vtt_match.group(1)
                
                # Video bulunamazsa sayfayı HTML parser ile de kontrol et
                if not video_link:
                    soup_iframe = BeautifulSoup(iframe_html, 'html.parser')
                    # Bu noktada, eğer linkler bir JS değişkeni içine gömülüyse, 
                    # o değişkeni bulmak için daha fazla regex gerekebilir.

                # Önceki film sayfasına geri dön (Sonraki filme geçmeden önce temizlik)
                driver.back()

        # Eğer iframe yoluyla bulunamazsa, kaynak kodun tamamında arama yap (Yedek)
        if not video_link:
             page_source = driver.page_source
             m3u8_match_direct = re.search(r'["\'](https?://[^"\']*\.m3u8|https?://[^"\']*\.mpd)["\']', page_source)
             if m3u8_match_direct:
                video_link = m3u8_match_direct.group(1)


    except Exception as e:
        print(f"  -> Video linki çekilirken hata oluştu: {e}")
        
    return video_link, subtitle_link

def create_m3u_file(film_list):
    """Veri listesini M3U çalma listesi formatına dönüştürür ve dosyaya yazar. Posteri tvg-logo olarak kullanır."""
    m3u_content = "#EXTM3U\n"
    
    for film in film_list:
        if film['Video_Link']:
            # M3U formatı: #EXTINF:-1, [Türler] Film Adı (Yıl)
            title = f"{film['Türleri']} {film['Adı']} ({film['Yılı']})"
            
            # #EXTINF satırı: Poster (tvg-logo) ve diğer meta veriler buraya eklenir.
            m3u_content += f'#EXTINF:-1 tvg-id="{film["Adı"]}" tvg-logo="{film["Poster"]}" group-title="{film["Türleri"]}",{title}\n'
            
            # Altyazı linkini referans olarak yorum satırı veya özel etiket olarak ekle
            if film['Altyazı_Link']:
                 m3u_content += f'#EXTM3U_SUBTITLE:{film["Altyazı_Link"]}\n'
                 
            # Klasik M3U8 linki (Orijinal içerik)
            m3u_content += f"{film['Video_Link']}\n"
    
    file_path = "hdfilmizle_playlist.m3u"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(m3u_content)
    
    print(f"\n[BAŞARILI] {len(film_list)} filmlik M3U dosyası oluşturuldu: {file_path}")
    return file_path

def main_scraper():
    """Ana kazıma sürecini yönetir."""
    driver = setup_driver()
    if not driver:
        return

    try:
        # 1. Ana Sayfadan Film Listesini Çekme
        print(f"\n[ADIM 1] Ana Sayfa Filmleri Çekiliyor: {TARGET_URL}")
        driver.get(TARGET_URL)

        # HTML'i al ve Beautiful Soup ile ayrıştır
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Her bir film kartını seçmek için benzersiz seçiciyi kullan
        film_kartlari = soup.select('a.poster.col-6.col-sm-3')
        
        if not film_kartlari:
            print("HATA: Ana sayfadan film kartı bulunamadı. Seçiciyi kontrol edin.")
            return
            
        print(f"-> Ana sayfada {len(film_kartlari)} film kartı bulundu. (İlk 5 film işleniyor.)")

        kazinan_filmler = []
        
        # Sadece ilk 5 filmi test etmek için
        for i, kart in enumerate(film_kartlari[:5]): 
            print(f"\n--- Film {i+1}/{len(film_kartlari[:5])} İşleniyor: {kart.get('title')} ---")
            
            # Veri çekme (Poster linki buraya eklendi)
            
            # A. Film URL'si ve Başlıklar
            film_url_path = kart.get('href')
            film_url = f"https://www.hdfilmizle.to{film_url_path}"
            film_adi = kart.select_one('h2.title').get_text(strip=True) if kart.select_one('h2.title') else "N/A"
            film_yili = kart.select_one('.poster-year').get_text(strip=True) if kart.select_one('.poster-year') else "N/A"
            film_turleri = kart.select_one('.poster-genres').get_text(strip=True) if kart.select_one('.poster-genres') else "N/A"
            
            # B. Poster Linkini Çekme
            # <img ... data-src="/v/502074/poster/thumb/fantastik-dortlu-ilk-adimlar.jpg" ...>
            poster_img = kart.select_one('img.lazyloaded') # veya img.ls-is-cached.lazyloaded
            poster_link = None
            if poster_img:
                # Poster URL'sini data-src veya src özelliklerinden al
                img_path = poster_img.get('data-src') or poster_img.get('src')
                if img_path and img_path.startswith('/'):
                    poster_link = f"https://www.hdfilmizle.to{img_path}"
                else:
                    poster_link = img_path # Tam URL ise olduğu gibi al
            
            # 2. Video ve Altyazı Linklerini Çekme
            video_link, subtitle_link = find_player_links(driver, film_url)
            
            kazinan_filmler.append({
                "Adı": film_adi,
                "Yılı": film_yili,
                "Türleri": film_turleri,
                "URL": film_url,
                "Poster": poster_link,
                "Video_Link": video_link,
                "Altyazı_Link": subtitle_link
            })
            
            print(f"  -> Sonuç: {'BAŞARILI' if video_link else 'BAŞARISIZ'}")
            print(f"  -> Video Linki: {video_link or 'Bulunamadı'}")
            print(f"  -> Altyazı Linki: {subtitle_link or 'Bulunamadı'}")
            # time.sleep(1) # Örtülü bekleme kullanıldığı için bu satıra gerek kalmadı

        # 3. M3U Dosyasını Hazırlama
        print("\n[ADIM 3] M3U Dosyası Hazırlanıyor...")
        create_m3u_file(kazinan_filmler)

    finally:
        driver.quit()

if __name__ == "__main__":
    main_scraper()