import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from processor import VisionProcessor

class ContextWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        # Eğer veritabanı dosyası güncellenirse (save işlemi bitti demektir)
        if "contexts.db" in event.src_path:
            print("Kayıt işlemi tespit edildi, ekran görüntüsü alınıyor...")
            vp = VisionProcessor()
            img = vp.capture_and_preprocess()
            vp.save_for_ai(img)

# Projenin ana klasörünü izle
path = "../../data" 
event_handler = ContextWatcher()
observer = Observer()
observer.schedule(event_handler, path, recursive=False)
observer.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()