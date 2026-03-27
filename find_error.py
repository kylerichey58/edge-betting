import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
total = len(lines)
print("Total lines:", total)

# Show lines around 2256
start = max(0, 2250)
end = min(total, 2262)
print("\nLines 2250-2262:")
for i in range(start, end):
    print(str(i+1).rjust(4), ":", repr(lines[i][:100]))

print()

# Find ALL var declarations that might be duplicated in same scope
import re
var_decls = {}
for i, line in enumerate(lines):
    matches = re.findall(r'\bvar\s+(\w+)\s*=', line)
    for m in matches:
        if m not in var_decls:
            var_decls[m] = []
        var_decls[m].append(i+1)

print("Variables declared more than once:")
for v, lns in var_decls.items():
    if len(lns) > 1:
        print(f"  '{v}' declared {len(lns)} times at lines: {lns[:10]}")
