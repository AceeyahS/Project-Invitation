import subprocess,re
subprocess.check_call(['node_modules/.bin/esbuild','src/scene.js','--bundle','--minify','--format=iife','--target=es2020','--outfile=/tmp/scene.bundle.js','--log-level=warning'])
b=open('/tmp/scene.bundle.js').read().replace('</script','<\\/script')
t=open('index.src.html').read().replace('/*__SCENE__*/',lambda m:b) if False else open('index.src.html').read()
t=t.replace('/*__SCENE__*/',b)
open('/home/claude/invite/index.html','w').write(t)
print('built',len(t)//1024,'KB')
