import os

folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'EDGE-Platform.html')

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Size:", len(content))

# THE REAL FIX: The tab CSS uses !important display:none
# But showTab sets style.display='block' which SHOULD override !important
# HOWEVER - if the tab div has inline style="display:none" already set
# AND the CSS says display:none !important
# Then setting style.display='block' via JS DOES override !important (inline beats stylesheet)
# So the issue must be something else entirely

# Let's check: maybe the problem is that ALL tabs have display:none
# and when we set tab.style.display='block' it works
# but then initCharts or renderBankroll is called and it does something wrong

# SIMPLEST POSSIBLE FIX: Remove !important from tab CSS
# and make showTab use classList only (the original approach)
content = content.replace(
    '.tab{display:none !important}',
    '.tab{display:none}'
)
content = content.replace(
    '.tab.active{display:block !important}',
    '.tab.active{display:block}'
)
print("Removed !important from tab CSS")

# Replace showTab with the SIMPLEST possible version
start = content.find('function showTab(name)')
end = content.find('\n}\n', start) + 3
simple_show = '''function showTab(name) {
  var tabs = document.querySelectorAll('.tab');
  for(var i=0;i<tabs.length;i++){
    tabs[i].classList.remove('active');
    tabs[i].removeAttribute('style');
  }
  var btns = document.querySelectorAll('.nav-btn');
  for(var j=0;j<btns.length;j++) btns[j].classList.remove('active');
  var t = document.getElementById('tab-'+name);
  if(t) t.classList.add('active');
  var bs = document.querySelectorAll('.nav-btn');
  for(var k=0;k<bs.length;k++){
    if(bs[k].textContent.toLowerCase().replace(/ /g,'').indexOf(name)!==-1)
      bs[k].classList.add('active');
  }
}
'''
content = content[:start] + simple_show + content[end:]
print("Replaced showTab with simplest version")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done! Size:", len(content))
print("Chrome: http://localhost:8080/EDGE-Platform.html")
print("Ctrl+Shift+R then click tabs")
