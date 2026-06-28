"""Fine-tune MobileNetV3 on your own images (transfer learning).

Expected data layout (torchvision ImageFolder):

  data/
    train/
      <class_a>/  img1.jpg img2.jpg ...
      <class_b>/  ...
    val/
      <class_a>/  ...
      <class_b>/  ...

The class folder names become the model's labels (sorted alphabetically). For a
content filter you might use e.g. `allow/` and `block/`, or `safe/` and `nsfw/`.

Examples:
  # Train only the classifier head (fast, good for small datasets):
  python fine_tune.py --data data --variant large --freeze --epochs 10

  # Fine-tune the whole network (needs more data / time):
  python fine_tune.py --data data --variant small --epochs 20 --lr 3e-4
"""

import argparse
import json
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

# Normalization the ImageNet-pretrained weights were trained with.
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def get_weights(variant):
    return (
        models.MobileNet_V3_Small_Weights.DEFAULT
        if variant == "small"
        else models.MobileNet_V3_Large_Weights.DEFAULT
    )


def build_model(variant, num_classes, freeze):
    weights = get_weights(variant)
    factory = models.mobilenet_v3_small if variant == "small" else models.mobilenet_v3_large
    model = factory(weights=weights)
    if freeze:
        for param in model.features.parameters():
            param.requires_grad = False
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def make_loaders(data_dir, image_size, batch_size, workers):
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(image_size),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize(int(image_size * 1.14)),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    root = Path(data_dir)
    train_ds = datasets.ImageFolder(root / "train", transform=train_tf)
    val_ds = datasets.ImageFolder(root / "val", transform=eval_tf)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                          num_workers=workers, pin_memory=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                        num_workers=workers, pin_memory=True)
    return train_ds, val_ds, train_dl, val_dl


def run_epoch(model, loader, device, criterion, optimizer=None):
    is_train = optimizer is not None
    model.train(is_train)
    total, correct, loss_sum = 0, 0, 0.0
    with torch.set_grad_enabled(is_train):
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)
            if is_train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            loss_sum += loss.item() * images.size(0)
            correct += (outputs.argmax(1) == labels).sum().item()
            total += images.size(0)
    return loss_sum / max(total, 1), correct / max(total, 1)


def main():
    p = argparse.ArgumentParser(description="Fine-tune MobileNetV3 with transfer learning.")
    p.add_argument("--data", default="data", help="dataset root containing train/ and val/")
    p.add_argument("--variant", choices=["small", "large"], default="large")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--image-size", type=int, default=224)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--freeze", action="store_true", help="freeze backbone, train only the head")
    p.add_argument("--out", default="runs", help="directory for checkpoints")
    p.add_argument("--device", default=None, help="cuda | cpu (auto-detected if omitted)")
    args = p.parse_args()

    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    print(f"Device: {device}")

    train_ds, val_ds, train_dl, val_dl = make_loaders(
        args.data, args.image_size, args.batch_size, args.workers
    )
    classes = train_ds.classes
    print(f"Classes ({len(classes)}): {classes}")
    print(f"Train: {len(train_ds)} images | Val: {len(val_ds)} images")

    model = build_model(args.variant, len(classes), args.freeze).to(device)
    criterion = nn.CrossEntropyLoss()
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classes.json").write_text(json.dumps(classes, indent=2))

    best_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        tr_loss, tr_acc = run_epoch(model, train_dl, device, criterion, optimizer)
        va_loss, va_acc = run_epoch(model, val_dl, device, criterion)
        scheduler.step()
        print(f"Epoch {epoch:02d}/{args.epochs} "
              f"| train loss {tr_loss:.4f} acc {tr_acc:.3f} "
              f"| val loss {va_loss:.4f} acc {va_acc:.3f}")

        if va_acc >= best_acc:
            best_acc = va_acc
            torch.save({
                "variant": args.variant,
                "classes": classes,
                "image_size": args.image_size,
                "mean": IMAGENET_MEAN,
                "std": IMAGENET_STD,
                "state_dict": model.state_dict(),
            }, out_dir / "best.pt")
            print(f"  saved best.pt (val acc {best_acc:.3f})")

    print(f"Done. Best val accuracy: {best_acc:.3f}")
    print(f"Checkpoint: {out_dir / 'best.pt'}")
    print("Next: python export_onnx.py --checkpoint runs/best.pt")


if __name__ == "__main__":
    main()
