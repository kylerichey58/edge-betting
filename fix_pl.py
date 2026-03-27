import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Total lines:", len(lines))
print("Line 1268:", repr(lines[1267].strip()[:80]))

fixes = 0
for i, line in enumerate(lines):
    # Fix any line that reads b.pl without null safety
    if 'b.pl > 0' in line and 'pl ||' not in line and 'const pl' not in line:
        lines[i] = line.replace('b.pl > 0', '(b.pl||0) > 0').replace('b.pl < 0', '(b.pl||0) < 0')
        print(f"Fixed line {i+1}: {repr(lines[i].strip()[:80])}")
        fixes += 1
    if 'b.pl.toFixed' in line:
        lines[i] = line.replace('b.pl.toFixed', '(b.pl||0).toFixed')
        print(f"Fixed toFixed line {i+1}")
        fixes += 1

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\nFixed {fixes} lines")
print("Done! Hard refresh Chrome.")
