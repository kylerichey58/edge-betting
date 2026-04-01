import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')
print("Reading:", path)

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("File size:", len(content), "bytes")
fixes = 0

# FIX 1: Tab CSS
if '.tab{display:none}' in content:
    content = content.replace('.tab{display:none}', '.tab{display:none !important}')
    content = content.replace('.tab.active{display:block}', '.tab.active{display:block !important}')
    print("FIX 1 applied: Tab CSS")
    fixes += 1
else:
    print("FIX 1: Already applied or not found")

# FIX 2: Replace showTab function
start = content.find('function showTab(name)')
if start != -1:
    end = content.find('\n}\n', start) + 3
    new_fn = 'function showTab(name) {\n  document.querySelectorAll(".tab").forEach(function(t){t.style.display="none";t.classList.remove("active");});\n  document.querySelectorAll(".nav-btn").forEach(function(b){b.classList.remove("active");});\n  var tab = document.getElementById("tab-"+name);\n  if(tab){tab.style.display="block";tab.classList.add("active");console.log("Tab opened:",name);}\n  else{console.error("Tab not found: tab-"+name);}\n  document.querySelectorAll(".nav-btn").forEach(function(b){if(b.textContent.toLowerCase().replace(/ /g,"").indexOf(name)!==-1)b.classList.add("active");});\n  if(name==="dashboard")setTimeout(initCharts,100);\n  if(name==="tracker"&&typeof renderTracker==="function")renderTracker();\n  if(name==="bankroll"&&typeof renderBankroll==="function")renderBankroll();\n}\n'
    content = content[:start] + new_fn + content[end:]
    print("FIX 2 applied: showTab replaced")
    fixes += 1
else:
    print("FIX 2: showTab not found")

# Write the fixed file
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("")
print("Done! Fixes applied:", fixes)
print("New file size:", len(content), "bytes")
print("")
print("Go to Chrome: http://localhost:8080/EDGE-Platform.html")
print("Press Ctrl+Shift+R and test the tabs!")
