from pathlib import Path
import json, subprocess, shutil

src=Path(__file__).with_name('program_generation_e2e.py').read_text(encoding='utf-8')
prefix=src.split('results=[]; start=',1)[0]
ns={}
exec(compile(prefix,'/tmp/astra_real_program_eval.py','exec'),ns)
ROOT=ns['ROOT']; SPECS=ns['SPECS']; BIN=ROOT/'bin-revalidate'
BIN.mkdir(exist_ok=True)

def run(cmd,stdin='',timeout=20):
    p=subprocess.run(cmd,input=stdin,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    return p.returncode,p.stdout.strip(),p.stderr.strip()

def commands(spec,path):
    out=BIN/spec.name
    if spec.lang=='python':
        return ['/usr/bin/python3','-m','py_compile',str(path)],['/usr/bin/python3',str(path)]
    if spec.lang=='javascript':
        node=shutil.which('node'); return [node,'--check',str(path)],[node,str(path)]
    if spec.lang=='bash':
        return ['/usr/bin/bash','-n',str(path)],['/usr/bin/bash',str(path)]
    if spec.lang=='c':
        return ['/usr/bin/gcc','-std=c11','-Wall','-Wextra','-O0',str(path),'-o',str(out)],[str(out)]
    if spec.lang=='cpp':
        return ['/usr/bin/g++','-std=c++17','-Wall','-Wextra','-O0',str(path),'-o',str(out)],[str(out)]
    if spec.lang=='rust':
        return [shutil.which('rustc'),'--edition=2021',str(path),'-o',str(out)],[str(out)]
    raise ValueError(spec.lang)

results=[]
for i,s in enumerate(SPECS,1):
    p=ROOT/s.filename
    check,base=commands(s,p)
    rc,out,err=run(check)
    ok=(rc==0); failure='' if ok else f'compile rc={rc}: {err}'
    if ok:
        for n,c in enumerate(s.cases,1):
            rc,out,err=run(base+c.get('a',[]),c.get('i',''),8)
            if rc or out!=c['o']:
                ok=False; failure=f"case {n}: rc={rc} expected={c['o']!r} got={out!r} stderr={err!r}"
                break
    results.append({'index':i,'name':s.name,'lang':s.lang,'ok':ok,'failure':failure})
    print(f"[{i:02d}/50] {s.lang:<10} {s.name:<20} {'PASS' if ok else 'FAIL'}",flush=True)
    if not ok: print('  -> '+failure.replace('\n',' | ')[:420],flush=True)

summary={'total':50,'passed':sum(r['ok'] for r in results),'failed':sum(not r['ok'] for r in results)}
(ROOT/'revalidated.json').write_text(json.dumps({'summary':summary,'results':results},ensure_ascii=False,indent=2))
print('SUMMARY',json.dumps(summary),flush=True)
