import os
import torch
# --- Patch for torchvision compatibility issue ---
if not hasattr(torch.library, 'register_fake'):
    torch.library.register_fake = lambda name: lambda func: func
# -------------------------------------------------
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
import matplotlib.pyplot as plt
import numpy as np

import json

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))

# Load Organs dynamically from classes.json
CLASSES_PATH = os.path.join(current_dir, "classes.json")
if os.path.exists(CLASSES_PATH):
    with open(CLASSES_PATH, "r", encoding='utf-8') as f:
        ORGANS = json.load(f)
else:
    # PanNuke Organs (19 classes) fallback
    ORGANS = [
        "Adrenal-gland", "Bile-duct", "Bladder", "Breast", "Cervix",
        "Colon", "Esophagus", "HeadNeck", "Kidney", "Liver",
        "Lung", "Ovarian", "Pancreatic", "Prostate", "Skin",
        "Stomach", "Testis", "Thyroid", "Uterus"
    ]

def setup_vit_model(num_classes=19, device="cpu", weights_path=None):
    print("Loading pre-trained Vision Transformer (ViT-B/16)...")
    # Load pretrained ViT
    weights = models.ViT_B_16_Weights.DEFAULT
    model = models.vit_b_16(weights=weights)
    
    # Modify the classification head for 19 organs
    # ViT's head is stored in model.heads
    in_features = model.heads.head.in_features
    model.heads.head = nn.Linear(in_features, num_classes)
    
    # Load the fine-tuned weights if they exist
    if weights_path and os.path.exists(weights_path):
        print(f"Loading fine-tuned weights from {weights_path}...")
        model.load_state_dict(torch.load(weights_path, map_location=device))
    else:
        print("WARNING: Fine-tuned weights not found. Using random head.")
        
    model = model.to(device)
    model.eval() # Set to evaluation mode
    
    return model, weights.transforms()

def predict_organ(image_path, model, transform, device="cpu"):
    image = Image.open(image_path).convert('RGB')
    
    # Apply standard ViT transforms (resize, crop, normalize)
    input_tensor = transform(image).unsqueeze(0).to(device)
    
    with torch.no_grad():
        output = model(input_tensor)
        # Convert logits to probabilities
        probabilities = torch.nn.functional.softmax(output[0], dim=0)
        
    return image, probabilities.cpu().numpy()

def visualize_prediction(image, probabilities, output_path, true_organ=None):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot image
    ax1.imshow(image)
    ax1.axis('off')
    title = "Input Patch"
    if true_organ:
        title += f"\n(True Label: {true_organ})"
    ax1.set_title(title, fontsize=14)
    
    # Get top 5 predictions
    top5_idx = np.argsort(probabilities)[-5:][::-1]
    top5_probs = probabilities[top5_idx]
    top5_organs = [ORGANS[i] for i in top5_idx]
    
    # Plot probabilities
    y_pos = np.arange(len(top5_organs))
    bars = ax2.barh(y_pos, top5_probs, align='center', color='skyblue')
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(top5_organs, fontsize=12)
    ax2.invert_yaxis()  # labels read top-to-bottom
    ax2.set_xlabel('Probability', fontsize=12)
    ax2.set_title('ViT Organ Prediction Confidence', fontsize=14)
    ax2.set_xlim(0, 1.0)
    
    # Add value labels
    for bar in bars:
        width = bar.get_width()
        ax2.text(width + 0.01, bar.get_y() + bar.get_height()/2.,
                 f'{width:.2%}', ha='left', va='center', fontsize=10)
                 
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches='tight', dpi=150)
    plt.close()
    print(f"Saved visualization to: {output_path}")

if __name__ == "__main__":
    # Setup
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    OUTPUT_DIR = os.path.join(current_dir, "results")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load model
    WEIGHTS_PATH = os.path.join(current_dir, "best_vit_organ.pth")
    model, transform = setup_vit_model(num_classes=len(ORGANS), device=device, weights_path=WEIGHTS_PATH)
    
    # Check if we loaded trained weights
    print("\n--- NOTE ---")
    if os.path.exists(WEIGHTS_PATH):
        print("Successfully loaded the fine-tuned ViT model for Organ Classification.")
    else:
        print("The ViT classification head is newly initialized and NOT YET TRAINED on PanNuke organs.")
        print("The visualized predictions are demonstrations of the framework pipeline.")
    print("------------\n")
    
    # Test images (using original patches, not the tiny extracted ROIs)
    TEST_IMAGES_DIR = os.path.join(base_dir, "pannuke_yolo", "test", "images")
    test_files = [
        "fold1_1003_Esophagus.png",
        "fold1_1023_Pancreatic.png"
    ]
    
    for f in test_files:
        img_path = os.path.join(TEST_IMAGES_DIR, f)
        if os.path.exists(img_path):
            # Extract true organ from filename for display
            true_organ = f.split('_')[-1].split('.')[0]
            
            # Run inference
            img, probs = predict_organ(img_path, model, transform, device)
            
            # Visualize
            out_path = os.path.join(OUTPUT_DIR, f"vit_predict_{f}")
            visualize_prediction(img, probs, out_path, true_organ=true_organ)
        else:
            print(f"File not found: {img_path}")
            
    print("\nTransformer Organ Classification pipeline executed.")
