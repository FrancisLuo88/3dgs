import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python remove_mask_path.py <transforms.json>")
        return

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        return

    with open(path, 'r') as f:
        data = json.load(f)

    for frame in data['frames']:
        if 'mask_path' in frame:
            del frame['mask_path']

    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Successfully removed mask_path from {path}")

if __name__ == "__main__":
    main()
