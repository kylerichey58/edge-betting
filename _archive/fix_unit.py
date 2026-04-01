import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Line 2256:", repr(lines[2255].strip()))
print("Line 2255:", repr(lines[2254].strip()))

# Find ALL lines with 'var unit'
print("\nAll 'var unit' lines:")
for i, line in enumerate(lines):
    if 'var unit' in line:
        print(f"  Line {i+1}: {repr(line.strip()[:80])}")

# Fix: keep first 'var unit', change all others to just 'unit'
first_found = False
fixed = 0
for i, line in enumerate(lines):
    if 'var unit = bankroll.unit || 20;' in line or 'var unit = bankroll.unit||20;' in line:
        if first_found:
            lines[i] = line.replace('var unit =', 'unit =', 1)
            print(f"Fixed line {i+1}")
            fixed += 1
        else:
            first_found = True

print(f"\nFixed {fixed} duplicate var unit lines")

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done! Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then test tabs!")
