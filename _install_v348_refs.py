# One-off installer: V3.48.0 seven new heroines' canonical reference photos.
# Owner explicitly approved using their supplied (AI-generated) photos as-is.
# 00_<name>_canonical_face.png = face-weighted crop (top of the frame)
# 01_<name>_canonical_look.png = the full image
# Extra carousel shots for violetta (photos 2 and 3 of the same girl).
from pathlib import Path
from PIL import Image

SRC = Path(r"C:\Users\Woterson\AppData\Roaming\Qoder\SharedClientCache\cache\images\task-6ec")
DST = Path(__file__).resolve().parent / "data" / "references"
MAX_SIDE = 1280

# (source file, folder, base name, extra carousel shots list of source files)
ROSTER = [
    ("photo_2026-08-28_14-51-05-4631ee00.jpg", "violetta", "violetta",
     ["photo_2026-10-04_10-04-46-6f534020.jpg", "photo_2026-10-04_10-06-50 (2)-4d210c12.jpg"]),
    ("photo_2026-10-04_10-06-50-7456e7f4.jpg", "darina", "darina", []),
    ("photo_2026-10-04_10-13-23-3eaf6f47.jpg", "eva", "eva", []),
    ("photo_2026-10-04_10-13-07-7e17c073.jpg", "romina", "romina", []),
    ("photo_2026-10-04_10-12-53-3210d41f.jpg", "kristina", "kristina", []),
    ("2026-10-04_10-56-20-dbd362f7.png", "zlata", "zlata", []),
    ("2026-10-04_10-54-37-43af078d.png", "veronika", "veronika", []),
]


def load_fit(name: str) -> Image.Image:
    img = Image.open(SRC / name)
    img = img.convert("RGB")
    w, h = img.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def face_crop(img: Image.Image) -> Image.Image:
    # keep the top 58% of the frame, centred horizontally — face anchor
    w, h = img.size
    top = int(h * 0.58)
    return img.crop((0, 0, w, top))


for src_name, folder, base, extras in ROSTER:
    out = DST / folder
    out.mkdir(parents=True, exist_ok=True)
    full = load_fit(src_name)
    full.save(out / f"01_{base}_canonical_look.png", optimize=True)
    face_crop(full).save(out / f"00_{base}_canonical_face.png", optimize=True)
    for idx, extra in enumerate(extras, start=2):
        load_fit(extra).save(out / f"0{idx}_{base}_reference_{idx - 1}.png", optimize=True)
    print(f"{folder}: ok ({full.size[0]}x{full.size[1]})")
print("DONE")
