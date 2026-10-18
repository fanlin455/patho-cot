import os
import glob
from PIL import Image
from tqdm import tqdm

def find_and_remove_corrupted_images(dataset_dir):
    print(f"Scanning for corrupted images in: {dataset_dir}")
    
    # 查找所有 .tif 和 .png 图像
    image_paths = glob.glob(os.path.join(dataset_dir, "**", "*.*"), recursive=True)
    image_paths = [p for p in image_paths if p.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff'))]
    
    print(f"Found {len(image_paths)} images to check.")
    
    corrupted_count = 0
    for img_path in tqdm(image_paths, desc="Checking images"):
        try:
            with Image.open(img_path) as img:
                img.verify() # 尝试验证图像文件头是否完整
        except Exception as e:
            print(f"\nCorrupted image found: {img_path} - Error: {e}")
            try:
                os.remove(img_path)
                print(f"Deleted corrupted file: {img_path}")
                corrupted_count += 1
            except Exception as del_e:
                print(f"Failed to delete {img_path}: {del_e}")
                
    print(f"\nScan complete. Found and deleted {corrupted_count} corrupted images.")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "结直肠癌组织亚型数据集", "NCT-CRC-HE-100K")
    find_and_remove_corrupted_images(target_dir)
