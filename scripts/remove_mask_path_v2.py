import json
import sys
import os

def main():
    if len(sys.argv) < 2:
        print("Usage: python remove_mask_path.py <transforms.json_path>")
        return

    json_path = sys.argv[1]
    
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}")
        return

    with open(json_path, 'r') as f:
        data = json.load(f)

    count = 0
    if 'frames' in data:
        for frame in data['frames']:
            if 'mask_path' in frame:
                del frame['mask_path']
                count += 1
    
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Removed mask_path from {count} frames in {json_path}")

if __name__ == "__main__":
    main()
