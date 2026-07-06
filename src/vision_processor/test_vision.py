from processor import VisionProcessor

# Fabrikayı çalıştır
vp = VisionProcessor()
resim = vp.capture_and_preprocess()
vp.save_for_ai(resim)

print("Test başarılı! Resim başarıyla kaydedildi.")