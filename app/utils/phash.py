from PIL import Image
import imagehash
from io import BytesIO

def compute_phash_from_bytes(data: bytes) -> str:
    img = Image.open(BytesIO(data)).convert("RGB")
    return str(imagehash.phash(img))
