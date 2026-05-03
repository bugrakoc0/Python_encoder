# 🏗️ NinjaEncoder v8 - Advanced Python Obfuscation Suite
**NinjaEncoder**, Python kaynak kodlarını tersine mühendislik (reverse engineering) ve statik analiz yöntemlerine karşı korumak amacıyla geliştirilmiş, çok katmanlı bir şifreleme ve karmaşıklaştırma (obfuscation) aracıdır. Basit şifreleyicilerin aksine, kodun çalışma mantığını (AST) ve çalışma zamanı (Runtime) davranışlarını koruma altına alır.
## 🚀 Öne Çıkan Teknik Özellikler
NinjaEncoder v8, endüstri standartlarında ve deneysel güvenlik tekniklerini bir araya getirir:
### 1. AST (Abstract Syntax Tree) Manipülasyonu
Kodun mantıksal yapısını bozmadan, düğüm seviyesinde karmaşıklaştırma yapılır.
 * **Control Flow Flattening:** Kodun doğrusal akışını bozar, fonksiyon içindeki mantığı takip etmeyi imkansız hale getirir.
 * **Dead Code Injection:** Analiz araçlarını şaşırtmak için işlevsiz ama gerçek görünen kod blokları ekler.
### 2. Matematiksel Karmaşıklaştırma (MBA - Mixed Boolean-Arithmetic)
Basit aritmetik işlemler (örn: a + b), mantıksal ve bit düzeyinde çok karmaşık formüllere dönüştürülür. Bu sayede statik analiz araçları kodun gerçek amacını çözemez.
### 3. Çoklu Çalışma Zamanı Koruması (Runtime Protection)
 * **Anti-Debugging:** sys.gettrace() ve ctypes kullanarak aktif bir hata ayıklayıcı (debugger) olup olmadığını kontrol eder.
 * **Memory Protection:** Kritik bytecode'lar bellekten okunduktan hemen sonra ctypes.memset ile temizlenir.
 * **Integrity Check:** Dosya içeriğinde bir değişiklik yapılıp yapılmadığını SHA-256 imzalarıyla kontrol eder.
### 4. Hibrit Derleme ve Paketleme
 * **Cython & Nuitka Entegrasyonu:** Kodun kritik kısımlarını C/C++ seviyesine derleyerek makine koduna dönüştürür.
 * **Hyperion Layer:** Katmanlı şifreleme ile her çalıştırmada farklı bir başlangıç (seed) değeri kullanır.
## 🛠️ Kurulum
Projeyi klonlayın ve gerekli bağımlılıkları yükleyin:
```bash
git clone https://github.com/bugrakoc0/Pyhon_Encoder.git
cd Pyhon_Encoder
pip install -r requirements.txt

```
*Gerekli temel kütüphaneler: Cython, nuitka, pycryptodome, lief.*
## 📖 Kullanım Modları
NinjaEncoder farklı ihtiyaçlar için farklı koruma seviyeleri sunar:
| Mod | Açıklama | Güvenlik Seviyesi |
|---|---|---|
| --simple | Temel Base64 ve Zlib sıkıştırma. | ⭐ |
| --advanced | AES-256 şifreleme ve AST karmaşıklaştırma. | ⭐⭐⭐ |
| --ultimate | Tüm tekniklerin (Anti-Debug, MBA, Stego) birleşimi. | ⭐⭐⭐⭐⭐ |
| --nuitka | Kodu C++ üzerinden binary dosyaya (.exe/.so) derler. | ⭐⭐⭐⭐ |
**Örnek Komut:**
```bash
python Encoder.py --input script.py --output protected.py --ultimate

```
## 🛡️ Yasal Uyarı (Disclaimer)
Bu araç tamamen **eğitim** ve **kod güvenliği araştırmaları** amacıyla geliştirilmiştir. Yazılımın kötü amaçlı kullanımıyla ilgili hiçbir sorumluluk kabul edilmemektedir. Kullanıcılar, yerel yasalarına ve etik kurallara uymakla yükümlüdür.
## 👤 Geliştirici
 * **Geliştirici:** bugrakoc0
 * **Sürüm:** v8.0.0
 * **İlgi Alanları:** Siber Güvenlik, Python Internals, Encryption.
