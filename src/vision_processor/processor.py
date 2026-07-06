import os

import cv2
import mss
import numpy as np

class VisionProcessor:
    def capture_and_preprocess(self):
        # 1. Ekran görüntüsü al
        with mss.mss() as sct:
            # 1 numaralı monitörü seç
            monitor = sct.monitors[1]
            screenshot = np.array(sct.grab(monitor))
            
        # 2. Görüntüyü işle
        img = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        
        # 3. Kırpma (VS Code'u odaklamak için basit bir merkezleme)
        # Ekranın ortasındaki %80'lik kısmı alıyoruz
        h, w = img.shape[:2]
        crop = img[int(h*0.1):int(h*0.9), int(w*0.1):int(w*0.9)]
        
        # 4. Boyutlandır
        resized = cv2.resize(crop, (1024, 768))
        
        return resized

    def save_for_ai(self, image, filename="snapshot_ready.png"):

        save_dir = os.path.join(os.path.dirname(__file__), "data", "snapshots")
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        full_path = os.path.join(save_dir, filename)
        cv2.imwrite(full_path, image)
        return full_path