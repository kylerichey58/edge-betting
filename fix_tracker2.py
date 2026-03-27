import os, re

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# Find ALL currentSport and currentType declarations
print("All currentSport/currentType declarations:")
for i, line in enumerate(lines):
    if re.search(r'\b(let|var|const)\s+currentSport\b', line):
        print(f"  Line {i+1}: {repr(line.strip()[:80])}")
    if re.search(r'\b(let|var|const)\s+currentType\b', line):
        print(f"  Line {i+1}: {repr(line.strip()[:80])}")

# Find ALL let/const/var declarations that appear more than once
print("\nChecking for duplicate declarations...")
decls = {}
for i, line in enumerate(lines):
    matches = re.findall(r'\b(let|const|var)\s+(\w+)\s*=', line)
    for kw, name in matches:
        if name not in decls:
            decls[name] = []
        decls[name].append((i+1, kw, line.strip()[:60]))

dupes = {k: v for k, v in decls.items() if len(v) > 1}
print(f"Variables declared more than once: {len(dupes)}")
for name, occurrences in list(dupes.items())[:20]:
    print(f"  '{name}':")
    for ln, kw, text in occurrences:
        print(f"    Line {ln} ({kw}): {text}")
