"""List local cache files for quick manual inspection."""
from pathlib import Path


cache_dir = Path(__file__).resolve().parents[2] / "cache"

print("Cache directory: " + str(cache_dir))
print("")

if cache_dir.exists():
    print("EXISTS")
    files = [(path.name, path.stat().st_size) for path in cache_dir.iterdir() if path.is_file()]

    print(f"Found {len(files)} files")

    if files:
        print("")
        print("Files:")
        print("-" * 60)

        for name, size in files[:10]:
            size_str = f"{size}B"
            if size >= 1024:
                size_str = f"{size / 1024:.1f}KB"
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f}MB"

            print(f"  {name:30s}  {size_str:>10s}")
else:
    print("NOT EXISTS")
