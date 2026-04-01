import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Original size:", len(content))

# Fix duplicate 'var unit' declarations
# The first one should stay as 'var unit'
# All subsequent ones become just 'unit' (no var)
count = content.count('var unit = bankroll.unit || 20;')
print("Found", count, "var unit declarations")

if count > 1:
    # Replace all but the first
    first = content.find('var unit = bankroll.unit || 20;')
    rest = content[first+1:]
    rest_fixed = rest.replace('var unit = bankroll.unit || 20;', 'unit = bankroll.unit || 20;')
    content = content[:first+1] + rest_fixed
    print("Fixed", count-1, "duplicate var unit declarations")

# Also fix any other duplicate var declarations that might cause issues
for varname in ['var unit', 'var color', 'var sign']:
    remaining = content.count('var unit = bankroll.unit || 20;')
    if remaining <= 1:
        print("var unit count is now:", remaining, "- OK")
        break

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done! Size:", len(content))
print("")
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then F12 then click tabs")
