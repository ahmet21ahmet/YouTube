import requests
import yaml
import sys
import re

# --- Yardımcı Fonksiyonlar ---

def load_config(config_path='config.yml'):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"HATA: Config dosyası okunamadı: {e}")
        sys.exit(1)

def fetch_playlist(url):
    try:
        print(f"Kaynak liste indiriliyor...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"HATA: Liste indirilemedi: {e}")
        sys.exit(1)

def extract_stream_id(url):
    """
    URL'den sadece ID numarasını çeker (Örn: 714).
    """
    # index.m3u8 uzantısını ve sondaki slash'ı temizle
    clean = url.replace('/index.m3u8', '').rstrip('/')
    # En sondaki parça ID'dir
    return clean.split('/')[-1]

def parse_and_group_channels(source_content):
    """
    Kanalları kategorilerine (group-title) göre gruplandırır.
    Döndürdüğü yapı: { 'Spor Kanallari': [kanal1, kanal2], 'Ulusal': [kanal3] ... }
    """
    print("--- Liste Analiz Ediliyor ve Kategorileniyor ---")
    
    # Kategorileri tutacak sözlük
    grouped_channels = {}
    
    # Satırları işle
    lines = source_content.splitlines()
    last_extinf = None
    
    count = 0
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('#EXTINF:'):
            last_extinf = line
        elif last_extinf and not line.startswith('#'):
            # Bu bir URL satırı ve öncesinde EXTINF var
            
            # 1. Kategori Adını (group-title) bul
            # Regex hem tırnaklı (group-title="X") hem tırnaksız (group-title=X) yakalar
            group_match = re.search(r'group-title=["\']?(.*?)["\']?([,;]|$)', last_extinf, re.IGNORECASE)
            
            if group_match:
                group_name = group_match.group(1).strip()
            else:
                group_name = "DIGER" # Kategori bulunamazsa
            
            # 2. Kanal objesini oluştur
            channel_obj = {
                'extinf': last_extinf,
                'url': line
            }
            
            # 3. Gruba ekle
            if group_name not in grouped_channels:
                grouped_channels[group_name] = []
            
            grouped_channels[group_name].append(channel_obj)
            
            last_extinf = None
            count += 1
            
    print(f"Toplam {count} kanal, {len(grouped_channels)} farklı kategori altında toplandı.")
    return grouped_channels

def build_new_playlist(grouped_channels, base_url):
    """
    Gruplanmış kanalları yeni URL yapısıyla birleştirir.
    Türk kategorilerini en başa alır.
    """
    print("--- Yeni Liste Oluşturuluyor ---")
    
    base_url = base_url.rstrip('/')
    output_lines = ['#EXTM3U']
    
    # 1. Grup isimlerini ayır: Türk içerenler ve Diğerleri
    turkish_groups = []
    other_groups = []
    
    for group_name in grouped_channels.keys():
        # Küçük harfe çevirip kontrol et (case insensitive)
        lower_name = group_name.lower()
        if 'turk' in lower_name or 'türk' in lower_name or 'tr ' in lower_name:
            turkish_groups.append(group_name)
        else:
            other_groups.append(group_name)
            
    # Grupları kendi içinde alfabetik sırala (İsteğe bağlı, düzenli görünür)
    turkish_groups.sort()
    other_groups.sort()
    
    # 2. Listeyi oluşturma sırası: Önce Türk grupları, Sonra Diğerleri
    final_group_order = turkish_groups + other_groups
    
    for group_name in final_group_order:
        channels = grouped_channels[group_name]
        
        for channel in channels:
            # ID'yi ayıkla
            stream_id = extract_stream_id(channel['url'])
            
            if stream_id and stream_id.isdigit():
                # Orijinal EXTINF satırını aynen yaz (Kategori bilgisi burada saklı)
                output_lines.append(channel['extinf'])
                
                # Yeni URL'yi oluştur: Base + ID + index.m3u8
                new_url = f"{base_url}/{stream_id}/index.m3u8"
                output_lines.append(new_url)
            else:
                # ID bulunamazsa güvenli mod: Orijinal URL'yi yaz (veya atla)
                # print(f"Uyarı: ID okunamadı, atlanıyor: {channel['url']}")
                pass

    return "\n".join(output_lines)

def save_playlist(content, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"İşlem tamam! '{output_file}' dosyası oluşturuldu.")

# --- Ana Fonksiyon ---
def main():
    config = load_config()
    source_content = fetch_playlist(config['source_playlist_url'])
    
    # 1. Aşama: Kanalları kategorilere göre hafızada grupla
    grouped_data = parse_and_group_channels(source_content)
    
    # 2. Aşama: Yeni URL'leri oluştur ve sırala
    new_content = build_new_playlist(grouped_data, config['base_url'])
    
    save_playlist(new_content, config['output_file'])

if __name__ == "__main__":
    main()