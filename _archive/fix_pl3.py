import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix: add null guard for b itself at start of map
for i, line in enumerate(lines):
    if "filtered.map((b, i) => {" in line:
        print(f"Found map at line {i+1}")
        # Check what's already on next line
        print(f"Next line: {repr(lines[i+1].strip()[:80])}")
        # Replace the map with a filter to remove undefined first
        lines[i] = line.replace(
            'filtered.map((b, i) => {',
            'filtered.filter(b => b && b.game).map((b, i) => {'
        )
        print(f"Fixed: added .filter(b => b && b.game) before .map()")
        break

# Also find the trailing comma in BETS array that creates undefined entry
# Look for },\n]; pattern with extra comma
content = ''.join(lines)
import re
# Find the end of BETS array
bets_end = content.rfind('\n];\n\n// ─── STATE')
if bets_end != -1:
    # Check for trailing comma before ];
    chunk = content[bets_end-100:bets_end+5]
    print(f"\nBETS array end: {repr(chunk)}")
    if '},\n];' in chunk or '},\n\n];' in chunk:
        print("Found trailing comma in BETS array - this creates undefined entry!")
        content = content.replace('},\n];\n\n// ─── STATE', '}\n];\n\n// ─── STATE')
        content = content.replace('},\n\n];\n\n// ─── STATE', '}\n];\n\n// ─── STATE')
        lines = content.split('\n')
        lines = [l + '\n' for l in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
        print("Fixed trailing comma")

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("\nDone! Hard refresh Chrome.")

