import os
import torch
import torch.nn as nn
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, classification_report

# --- Patch for torchvision compatibility issue ---
if not hasattr(torch.library, 'register_fake'):
    torch.library.register_fake = lambda name: lambda func: func
# -------------------------------------------------

def evaluate_subtype_model():
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Evaluating Subtype Model on {device}...")
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "结直肠癌组织亚型数据集", "NCT-CRC-HE-100K")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(current_dir, "subtype_mobilenet_v3.pth")
    classes_path = os.path.join(current_dir, "subtype_classes.txt")
    
    if not os.path.exists(model_path):
        print(f"Error: Model not found at {model_path}. Please wait for training to finish.")
        return

    # Load classes
    with open(classes_path, "r") as f:
        classes = [line.strip() for line in f.readlines()]
    num_classes = len(classes)

    # Transform
    val_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    print("Loading test dataset (using a subset for quick evaluation)...")
    full_dataset = datasets.ImageFolder(data_dir, transform=val_transform)
    
    # We use the same random split logic but only take the val part
    train_size = int(0.8 * len(full_dataset))
    val_size = len(full_dataset) - train_size
    _, val_dataset = torch.utils.data.random_split(full_dataset, [train_size, val_size], generator=torch.Generator().manual_seed(42))
    
    batch_size = 64
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=4)

    # Initialize model
    model = models.mobilenet_v3_large(weights=None)
    in_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(in_features, num_classes)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model = model.to(device)
    model.eval()
    
    all_preds = []
    all_labels = []
    
    print("Running inference on validation set...")
    with torch.no_grad():
        for i, (inputs, labels) in enumerate(val_loader):
            inputs, labels = inputs.to(device), labels.to(device)
            outputs = model(inputs)
            _, predicted = torch.max(outputs, 1)
            
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
            
            if (i+1) % 50 == 0:
                print(f"Processed [{i+1}/{len(val_loader)}] batches...")

    # Metrics
    print("\n" + "="*50)
    print("Subtype Model Performance")
    print("="*50)
    report = classification_report(all_labels, all_preds, target_names=classes, digits=4)
    print(report)
    
    # Confusion Matrix
    cm = confusion_matrix(all_labels, all_preds)
    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=classes, yticklabels=classes)
    plt.title('Colorectal Cancer Subtype - Confusion Matrix', fontsize=15)
    plt.ylabel('True Subtype', fontsize=12)
    plt.xlabel('Predicted Subtype', fontsize=12)
    
    out_cm_path = os.path.join(current_dir, "subtype_confusion_matrix.png")
    plt.savefig(out_cm_path, bbox_inches='tight', dpi=150)
    plt.close()
    print(f"\nConfusion matrix saved to: {out_cm_path}")

if __name__ == "__main__":
    evaluate_subtype_model()
