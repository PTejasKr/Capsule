import os
import glob
from PIL import Image

brain_dir = r"C:\Users\punya\.gemini\antigravity\brain\bc00f49b-363e-4d6c-ac6a-bfef1ab4516d"
icons_dir = r"c:\Users\punya\Desktop\capsule\extension\icons"

# Get the latest jpg or png file
image_files = glob.glob(os.path.join(brain_dir, "*.jpg")) + glob.glob(os.path.join(brain_dir, "*.png"))
latest_image = max(image_files, key=os.path.getmtime)

print(f"Using image: {latest_image}")

img = Image.open(latest_image).convert("RGBA")

# Resize and save
sizes = [16, 48, 128]
for size in sizes:
    resized_img = img.resize((size, size), Image.Resampling.LANCZOS)
    output_path = os.path.join(icons_dir, f"icon{size}.png")
    resized_img.save(output_path, "PNG")
    print(f"Saved {output_path}")
