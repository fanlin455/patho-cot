import os
import requests
import zipfile
import sys
from tqdm import tqdm

def download_with_resume(url, file_path):
    headers = {}
    mode = 'wb'
    
    # 检查文件是否已经存在以进行断点续传
    if os.path.exists(file_path):
        downloaded_bytes = os.path.getsize(file_path)
        headers['Range'] = f'bytes={downloaded_bytes}-'
        mode = 'ab'
        print(f"Resuming download from {downloaded_bytes / (1024 * 1024):.1f} MB...")
    else:
        downloaded_bytes = 0

    response = requests.get(url, headers=headers, stream=True)
    
    # 获取总大小
    total_size = int(response.headers.get('content-length', 0)) + downloaded_bytes
    
    if response.status_code == 416:
        print("File is already fully downloaded.")
        return True
    
    if response.status_code not in [200, 206]:
        print(f"Failed to download. Status code: {response.status_code}")
        return False

    with open(file_path, mode) as file, tqdm(
        desc=os.path.basename(file_path),
        initial=downloaded_bytes,
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        try:
            for data in response.iter_content(chunk_size=1024):
                if data:
                    size = file.write(data)
                    bar.update(size)
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            print(f"\nConnection broken during download: {e}")
            return False # Return False to trigger a retry
    return True

def main():
    url = "https://zenodo.org/records/1214456/files/NCT-CRC-HE-100K.zip"
    
    # 使用相对路径：当前脚本所在的目录
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "结直肠癌组织亚型数据集")
    
    os.makedirs(target_dir, exist_ok=True)
    zip_path = os.path.join(target_dir, "NCT-CRC-HE-100K.zip")

    print(f"Target URL: {url}")
    
    # 无限循环重试，直到下载成功
    max_retries = 50
    retries = 0
    success = False
    
    while not success and retries < max_retries:
        success = download_with_resume(url, zip_path)
        if not success:
            retries += 1
            print(f"Retrying... ({retries}/{max_retries})")
            import time
            time.sleep(3) # Wait 3 seconds before retrying
            
    if not success:
        print("Download failed after maximum retries.")
        return

    print("Checking if extraction is needed...")
    try:
        # Check if it's a valid zip before attempting to extract
        if zipfile.is_zipfile(zip_path):
            print("Extracting zip file...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            print(f"Extraction complete! Dataset is ready at: {target_dir}")
        else:
             print("Error: The downloaded file is not a valid zip file or is incomplete. Try running the script again to resume.")
    except zipfile.BadZipFile:
        print("Error: The downloaded zip file is corrupted. Please delete it and try again.")

if __name__ == "__main__":
    main()
