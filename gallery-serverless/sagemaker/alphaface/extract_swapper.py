"""Keeps only the generator ("swapper") weights from the AlphaFace demo checkpoint (drops the
discriminator and optimiser state: 1.9 GB -> ~550 MB)."""
import sys

import torch

ckpt = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
torch.save(ckpt["swapper"], sys.argv[2])
print(f"Saved {len(ckpt['swapper'])} swapper tensors to {sys.argv[2]}")
