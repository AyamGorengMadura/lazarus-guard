from time import time

import cv2
import mediapipe as mp
import os
import numpy as np
import redis
from PIL import Image
import json
from pillow_heif import register_heif_opener
# ini atas gausah diubah ubah anj, kalo mau nambah modul pake venv jangan global.
# source venv/bin/activate  # buat linux
# venv\Scripts\activate  # buat windows (kalo pake terminal vsc pake yang linux aja)
# pip install opencv-python mediapipe pillow pillow-heif (kalo belom install, tapi kalo udah yaudah jangan diinstall lagi, ngapain juga)
r = redis.Redis(host="localhost", port=6379, decode_responses=True)
# ini biar supprt heic, tadi gabisa terus dibisain. caranya? adalah pokoknya.
register_heif_opener()

# Ini tuh buat arahin modelnya ngescan folder buat nyari foto, task model, ama folder buat nyimpen alert kalo ada orang asing yang ke-detect.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))

REGISTRY_PATH = os.path.join(BASE_DIR, "src", "registry")
MODEL_PATH = os.path.join(BASE_DIR, "configs", "face_landmarker_v2_with_blendshapes.task")

ALERTS_PATH = os.path.join(CURRENT_DIR, "alerts")

# Threshold cosine similarity buat matching — makin tinggi makin ketat
# 0.97 = recommended, turunin ke 0.95 kalo terlalu strict
SIMILARITY_THRESHOLD = 0.95


class LazarusGuard:

    def __init__(self):
        # known_signatures sekarang nyimpen list of embedding vectors (numpy array 936-dim)
        # bukan lagi tuple (r1, r2). biar ga muka gw mulu.
        self.known_signatures = {}

        # Setup Landmarker MediaPipe buat deteksi muka
        self.options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=3  # ini 3 aja, jangan dinaikin. ngelag su
        )
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(self.options)

        if not os.path.exists(ALERTS_PATH): os.makedirs(ALERTS_PATH)
        self.load_registry()

        self.last_published_identity = None
        self.last_unknown_publish_time = 0
        self.UNKNOWN_COOLDOWN = 5  # detik

    def get_face_embedding(self, landmarks):

        # ini pake 468 landmark yang diambil dari model, tiap landmark punya x,y,z. jadi total 468*3 = 1404 dimensi. tapi biar lebih ringan, kita cuma pake x dan y doang, jadi 468*2 = 936 dimensi. ini masih cukup kaya buat bedain muka orang, karena bentuk muka itu mostly ditentuin sama posisi relatif titik-titik landmarknya, bukan dari kedalaman z nya. jadi kita buang z nya biar lebih simpel dan cepet.
        # barangkali tanya gimana kerjanya, gw juga gatau. it's magic.
        # as long as it works, who cares?

        # Ambil centroid muka dulu buat normalisasi posisi kalo ga pake ini ntar bingung.
        xs = np.array([lm.x for lm in landmarks])
        ys = np.array([lm.y for lm in landmarks])
        cx, cy = xs.mean(), ys.mean()

        # Geser semua titik relatif ke centroid
        coords = np.array([(lm.x - cx, lm.y - cy) for lm in landmarks]).flatten()  # shape: (936,)

        # L2 normalize
        norm = np.linalg.norm(coords)
        if norm < 1e-6:
            return None  # muka ga kedeteksi proper, skip
        return coords / norm

    def cosine_similarity(self, vec_a, vec_b):
        """Cosine similarity antara 2 vector, range -1 sampai 1. makin deket 1 makin mirip."""
        return np.dot(vec_a, vec_b)  # udah L2-normalized, jadi dot product = cosine sim langsung

    def load_image_universal(self, img_path):
        """Baca JPG, PNG, atau HEIC dan ubah ke format OpenCV"""
        try:
            pil_img = Image.open(img_path)
            return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"[ERROR] Skip file {img_path}: {e}")
            return None

    def load_registry(self):
        print("[INFO] Memulai Multi-Embedding Encoding (v5 — 936-dim cosine mode)...")
        for person_name in os.listdir(REGISTRY_PATH):
            person_dir = os.path.join(REGISTRY_PATH, person_name)
            if os.path.isdir(person_dir):
                embeddings = []
                for file_name in os.listdir(person_dir):
                    if file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.heic')):
                        img = self.load_image_universal(os.path.join(person_dir, file_name))
                        if img is not None:
                            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                            res = self.landmarker.detect(mp_img)
                            if res.face_landmarks:
                                emb = self.get_face_embedding(res.face_landmarks[0])
                                if emb is not None:
                                    embeddings.append(emb)

                if embeddings:
                    self.known_signatures[person_name] = embeddings
                    print(f"[SUCCESS] {person_name}: {len(embeddings)} embeddings loaded.")

    def match_face(self, embedding):

        """
        Cari identity paling cocok dari registry.
        Return (name, similarity) — kalo ga ada yang lewat threshold, return ("ORANG ASING", best_score).
        Pake max similarity bukan first-match, biar lebih akurat.
        """
        best_name = "ORANG ASING"
        best_score = -1.0

        for name, emb_list in self.known_signatures.items():
            for saved_emb in emb_list:
                score = self.cosine_similarity(embedding, saved_emb)
                if score > best_score:
                    best_score = score
                    if score >= SIMILARITY_THRESHOLD:
                        best_name = name
                        # tambahin ini di match_face sebelum return
                        #best tuh maksudnya score seseorang mirip ke mana, kalo di atas threshold baru dianggap match, tapi tetep simpan best_score buat debug dan info. jadi kalo ada yang 0.95 tapi threshold 0.97, ga bakal dianggap match tapi tetep keliatan di debug log seberapa deketnya. ini penting buat tuning threshold ke depannya. btw poin gw dapet stabil di 0.99 sampe 1.0, rata rata orang lain dibawah itu meski bestnya masih gw karena minim foto di registry. jadi kalo mau lebih akurat, tinggal tambahin foto di registry, nanti embeddingnya bakal lebih rame dan beda dari orang lain. intinya jangan takut buat tambahin foto, malah bagus buat ningkatin akurasi. tapi tetep pastiin fotonya jelas muka orangnya, jangan yang blur atau terlalu jauh, biar embeddingnya bagus. tapi kalo mau paksa ai belajar, buat se plenger mungkin fotonya.
                        print(f"[DEBUG] best: {best_name} | score: {best_score:.4f}")
        return best_name, best_score

    def run_patrol(self):
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        print("[SYSTEM] Lazarus Guard Aktif. Tekan 'q' buat berenti.")


        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break


            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = self.landmarker.detect(mp_image)

            if result.face_landmarks:
                for face_landmarks in result.face_landmarks:
                    # 1. Extract embedding
                    emb = self.get_face_embedding(face_landmarks)
                    if emb is None:
                        continue

                    # 2. Bounding Box
                    x_coords = [lm.x for lm in face_landmarks]
                    y_coords = [lm.y for lm in face_landmarks]
                    xmin = int(min(x_coords) * frame.shape[1])
                    xmax = int(max(x_coords) * frame.shape[1])
                    ymin = int(min(y_coords) * frame.shape[0])
                    ymax = int(max(y_coords) * frame.shape[0])

                    # 3. Match
                    identity, score = self.match_face(emb)

                    should_publish = False
                    embedding_id = None

                    if identity != "ORANG ASING":
                        if identity != self.last_published_identity:
                            should_publish = True
                            embedding_id = identity
                            self.last_published_identity = identity
                    else:
                        now = time()  # bukan time.time()
                        if now - self.last_unknown_publish_time > self.UNKNOWN_COOLDOWN:
                            should_publish = True
                            embedding_id = f"unknown_{int(now)}"
                            self.last_unknown_publish_time = now
                        self.last_published_identity = None

                    if should_publish:
                        event_payload = {
                            "match": identity != "ORANG ASING",
                            "name": identity if identity != "ORANG ASING" else None,
                            "confidence": float(score),
                            "embedding_id": embedding_id
                        }
                        r.publish("event:face_detected", json.dumps(event_payload))

                    color = (0, 255, 0) if identity != "ORANG ASING" else (0, 0, 255)

                    # 4. Render UI
                    cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), color, 2)
                    label = f"{identity.upper()} ({score:.2f})"  # tampilin score buat debug
                    (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                    cv2.rectangle(frame, (xmin, ymax), (xmin + w, ymax + h + 10), color, -1)
                    cv2.putText(frame, label, (xmin, ymax + h + 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            cv2.imshow('Core_LZ-Cy: Lazarus Guard v4.x', frame)
            # ini ditambahin "S" buat foto ganteng, biar ga repot repot drag and drop foto ke registry, tinggal pose depan kamera terus tekan "S" buat simpan fotonya langsung ke registry. nanti pas match juga bakal lebih akurat karena fotonya langsung dari kamera (webcam gw burik), ga perlu takut beda angle atau pencahayaan. tapi tetep pastiin fotonya jelas muka orangnya, jangan yang blur atau terlalu jauh, biar embeddingnya bagus. tapi kalo mau paksa ai belajar, buat se plenger mungkin fotonya.
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):  # pencet s buat eses, pencet q buat qabur
                save_path = os.path.join(REGISTRY_PATH, "Satura", f"webcam_{int(cv2.getTickCount())}.jpg") # ini sementara disave ke wajah gw buat tes
                cv2.imwrite(save_path, frame)
                print(f"[SAVED] {save_path}")

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    guard = LazarusGuard()
    guard.run_patrol()
