import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Lines 1265-1275:")
for i in range(1264, 1275):
    print(f"{i+1}: {repr(lines[i].strip()[:100])}")

# The fix: find the .map() in renderTracker and add null check at the top
fixes = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    # Fix b.pl.toFixed - this is the crash point
    if 'b.pl.toFixed' in line:
        lines[i] = line.replace('b.pl.toFixed', '(b.pl||0).toFixed')
        print(f"Fixed b.pl.toFixed at line {i+1}")
        fixes += 1
    # Fix b.pl > 0 patterns
    if 'b.pl > 0' in line and '(b.pl||0)' not in line:
        lines[i] = line.replace('b.pl > 0', '(b.pl||0) > 0')
        print(f"Fixed b.pl > 0 at line {i+1}")
        fixes += 1
    if 'b.pl < 0' in line and '(b.pl||0)' not in line:
        lines[i] = line.replace('b.pl < 0', '(b.pl||0) < 0')
        print(f"Fixed b.pl < 0 at line {i+1}")
        fixes += 1

# Also add a guard at the start of the map function
for i, line in enumerate(lines):
    if "filtered.map((b, i) => {" in line:
        # Add null check on next line
        next_line = lines[i+1] if i+1 < len(lines) else ''
        if 'if(!b)' not in next_line and 'const pl' not in next_line:
            lines.insert(i+1, "    if(!b || b.pl === undefined) b = {...b, pl: 0};\n")
            print(f"Added null guard after line {i+1}")
            fixes += 1
            break

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\nFixed {fixes} issues")
print("Hard refresh Chrome!")
