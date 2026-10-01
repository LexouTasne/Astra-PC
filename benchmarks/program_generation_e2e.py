from __future__ import annotations
import json, re, shutil, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from astra_pc.ai.agent import AstraBrain
from astra_pc.ai.ollama_client import OllamaClient
from astra_pc.skills.files import FilesSkill

ROOT=Path("/home/lex/Astra-Real-E2E-50-final"); BIN=ROOT/"bin"
ROOT.mkdir(parents=True,exist_ok=True); BIN.mkdir(parents=True,exist_ok=True)
client=OllamaClient("qwen2.5-coder:3b","http://127.0.0.1:11434",120,"5m")
CODE_SYSTEM="""Você é o motor de programação do Astra. Gere código executável e correto para o runtime pedido. Siga exatamente o formato de entrada e saída fornecido. Use argv/stdin exatamente como descrito. Não explique nada. Não use markdown. Não invente APIs ou dependências. Prefira código curto, direto e compatível com biblioteca padrão."""
files=FilesSkill()

@dataclass
class Spec:
    name:str; lang:str; filename:str; requirement:str; cases:list[dict]

def S(name,lang,filename,req,cases): return Spec(name,lang,filename,req,cases)

SPECS=[
S("fleet_summary","python","fleet_summary.py","Receba um argumento com veículos separados por vírgula status:km. Conte active e maintenance, some km. Imprima active=N maintenance=N total_km=N.",[{"a":["active:120,maintenance:80,active:150"],"o":"active=2 maintenance=1 total_km=350"},{"a":["maintenance:10,maintenance:20"],"o":"active=0 maintenance=2 total_km=30"}]),
S("inventory_restock","python","inventory_restock.py","Receba itens nome:estoque:minimo separados por vírgula. Imprima nomes com estoque<minimo em ordem alfabética separados por vírgula; se nenhum, OK.",[{"a":["ssd:2:5,mouse:1:3,cabo:8:2"],"o":"mouse,ssd"},{"a":["ssd:8:5,mouse:3:3"],"o":"OK"}]),
S("expense_report","python","expense_report.py","Receba decimais separados por vírgula. Imprima total=X.XX average=X.XX.",[{"a":["10,20,30"],"o":"total=60.00 average=20.00"},{"a":["2.5,7.5"],"o":"total=10.00 average=5.00"}]),
S("log_counter","python","log_counter.py","Leia stdin, linhas começam INFO/WARN/ERROR. Imprima INFO=N WARN=N ERROR=N.",[{"i":"INFO start\nERROR bad\nWARN slow\nERROR fail\n","a":[],"o":"INFO=1 WARN=1 ERROR=2"},{"i":"INFO a\nINFO b\n","a":[],"o":"INFO=2 WARN=0 ERROR=0"}]),
S("csv_revenue","python","csv_revenue.py","Leia CSV stdin com cabeçalho product,qty,price. Some qty*price e imprima revenue=X.XX usando biblioteca padrão.",[{"i":"product,qty,price\nssd,2,10.50\nmouse,3,5\n","a":[],"o":"revenue=36.00"},{"i":"product,qty,price\nx,1,2.25\n","a":[],"o":"revenue=2.25"}]),
S("task_tracker","python","task_tracker.py","Receba statuses done,pending,doing separados por vírgula. Imprima done=N pending=N doing=N.",[{"a":["done,pending,done,doing"],"o":"done=2 pending=1 doing=1"},{"a":["pending,pending"],"o":"done=0 pending=2 doing=0"}]),
S("ip_validator","python","ip_validator.py","Receba IPv4 em argv[1], use biblioteca padrão e imprima VALID ou INVALID.",[{"a":["192.168.1.10"],"o":"VALID"},{"a":["999.2.3.4"],"o":"INVALID"}]),
S("word_freq","python","word_freq.py","Receba frase em argv[1], ignore caixa, palavras alfanuméricas. Imprima palavra mais frequente como word=N; empate alfabeticamente.",[{"a":["Astra code code test Astra code"],"o":"code=3"},{"a":["z b z b"],"o":"b=2"}]),
S("dedupe_sorted","python","dedupe_sorted.py","Receba inteiros em argumentos, remova duplicados, ordene e imprima separados por vírgula.",[{"a":["3","1","3","2"],"o":"1,2,3"},{"a":["10","-1","10","0"],"o":"-1,0,10"}]),
S("schedule_conflicts","python","schedule_conflicts.py","Receba intervalos start-end separados por vírgula. Conte pares que se sobrepõem estritamente; encostar não conta. Imprima conflicts=N.",[{"a":["1-4,3-5,5-8"],"o":"conflicts=1"},{"a":["1-2,2-3,3-4"],"o":"conflicts=0"}]),
S("bank_balance","python","bank_balance.py","Receba transações decimais separadas por vírgula e imprima balance=X.XX.",[{"a":["100,-25.5,10"],"o":"balance=84.50"},{"a":["-5,2"],"o":"balance=-3.00"}]),
S("json_extract","python","json_extract.py","Receba JSON de objeto e uma chave. Imprima valor sem aspas ou MISSING.",[{"a":["{\"name\":\"Astra\",\"n\":2}","name"],"o":"Astra"},{"a":["{\"n\":2}","x"],"o":"MISSING"}]),

S("fleet_fuel","javascript","fleet_fuel.js","Node CLI. Receba pares km:litros separados por vírgula, imprima efficiency=X.XX = soma km/soma litros.",[{"a":["100:10,150:15"],"o":"efficiency=10.00"},{"a":["90:10,60:10"],"o":"efficiency=7.50"}]),
S("inventory_value","javascript","inventory_value.js","Node CLI. Receba qty:price separados por vírgula e imprima value=X.XX.",[{"a":["2:10.5,3:5"],"o":"value=36.00"},{"a":["1:2.25"],"o":"value=2.25"}]),
S("query_parser","javascript","query_parser.js","Node CLI. Receba URL em argv[2], ordene query keys alfabeticamente e imprima key=value por vírgula. Use URL padrão.",[{"a":["https://x.test/?b=2&a=1"],"o":"a=1,b=2"},{"a":["https://x.test/?z=ok"],"o":"z=ok"}]),
S("sales_agg","javascript","sales_agg.js","Node CLI. Registros product:amount separados por vírgula. Some por produto, ordene e imprima product=total com 2 casas por vírgula.",[{"a":["ssd:10,mouse:5,ssd:2.5"],"o":"mouse=5.00,ssd=12.50"},{"a":["a:1,b:2"],"o":"a=1.00,b=2.00"}]),
S("async_pipeline","javascript","async_pipeline.js","Node CLI. Inteiro n. Em Promise resolvida multiplique por 2, depois some 3 e imprima resultado.",[{"a":["5"],"o":"13"},{"a":["0"],"o":"3"}]),
S("event_queue","javascript","event_queue.js","Node CLI. Eventos separados por vírgula; remova duplicados preservando primeira ocorrência e imprima por >.",[{"a":["open,save,open,close"],"o":"open>save>close"},{"a":["a,a,b"],"o":"a>b"}]),
S("js_conflicts","javascript","schedule_conflicts.js","Node CLI. Intervalos start-end por vírgula; conte pares com sobreposição estrita, imprima conflicts=N.",[{"a":["1-4,3-5,5-8"],"o":"conflicts=1"},{"a":["1-2,2-3"],"o":"conflicts=0"}]),
S("group_count","javascript","group_count.js","Node CLI. JSON array de objetos com team. Conte por team, ordene e imprima team=N por vírgula.",[{"a":["[{\"team\":\"b\"},{\"team\":\"a\"},{\"team\":\"b\"}]"],"o":"a=1,b=2"},{"a":["[{\"team\":\"x\"}]"],"o":"x=1"}]),
S("palindrome","javascript","palindrome.js","Node CLI. Texto em um argumento; ignore não alfanuméricos e caixa. YES se palíndromo, senão NO.",[{"a":["A man, a plan, a canal: Panama"],"o":"YES"},{"a":["Astra"],"o":"NO"}]),
S("chunk_array","javascript","chunk_array.js","Node CLI. Primeiro arg tamanho chunk, demais itens. Chunks por | e itens por vírgula.",[{"a":["2","a","b","c","d","e"],"o":"a,b|c,d|e"},{"a":["3","1","2"],"o":"1,2"}]),

S("bash_sum","bash","sum.sh","Bash. Some argumentos inteiros e imprima sum=N.",[{"a":["1","2","3"],"o":"sum=6"},{"a":["-2","5"],"o":"sum=3"}]),
S("bash_max","bash","max.sh","Bash. Inteiros como argumentos, imprima max=N.",[{"a":["2","9","3"],"o":"max=9"},{"a":["-5","-2"],"o":"max=-2"}]),
S("bash_ext_count","bash","ext_count.sh","Bash. Nomes de arquivo como args; conte os terminados em .py, imprima py=N.",[{"a":["a.py","b.js","c.py"],"o":"py=2"},{"a":["x.txt"],"o":"py=0"}]),
S("bash_kv","bash","kv.sh","Bash. Args key=value, ordene por key e imprima por vírgula.",[{"a":["b=2","a=1"],"o":"a=1,b=2"},{"a":["x=ok"],"o":"x=ok"}]),
S("bash_logs","bash","logs.sh","Bash. Leia stdin; conte linhas ERROR e WARN, imprima ERROR=N WARN=N.",[{"i":"ERROR a\nWARN b\nINFO c\nERROR d\n","a":[],"o":"ERROR=2 WARN=1"},{"i":"INFO x\n","a":[],"o":"ERROR=0 WARN=0"}]),
S("bash_csv_sum","bash","csv_sum.sh","Bash. Leia stdin CSV sem cabeçalho nome,valor. Some coluna 2 e imprima total=N.",[{"i":"a,2\nb,3\n","a":[],"o":"total=5"},{"i":"x,10\n","a":[],"o":"total=10"}]),
S("bash_backup","bash","backup_name.sh","Bash. Receba caminho e imprima basename seguido de .bak.",[{"a":["/home/lex/file.txt"],"o":"file.txt.bak"},{"a":["abc"],"o":"abc.bak"}]),
S("bash_disk","bash","disk_level.sh","Bash. Percentual inteiro: OK se <70, WARN 70-89, CRIT >=90.",[{"a":["50"],"o":"OK"},{"a":["75"],"o":"WARN"},{"a":["95"],"o":"CRIT"}]),

S("c_fleet","c","fleet.c","C11 CLI. Args active/maintenance, conte e imprima active=N maintenance=N.",[{"a":["active","maintenance","active"],"o":"active=2 maintenance=1"},{"a":["maintenance"],"o":"active=0 maintenance=1"}]),
S("c_average","c","average.c","C11 CLI. Inteiros como args, imprima average=X.XX.",[{"a":["10","20","30"],"o":"average=20.00"},{"a":["1","2"],"o":"average=1.50"}]),
S("c_minmax","c","minmax.c","C11 CLI. Inteiros, imprima min=N max=N.",[{"a":["3","-1","8"],"o":"min=-1 max=8"},{"a":["5"],"o":"min=5 max=5"}]),
S("c_vowels","c","vowels.c","C11 CLI. Texto argv[1], conte vogais aeiou ignorando caixa, imprima vowels=N.",[{"a":["Astra"],"o":"vowels=2"},{"a":["rhythm"],"o":"vowels=0"}]),
S("c_reverse","c","reverse.c","C11 CLI. String argv[1], imprima invertida.",[{"a":["astra"],"o":"artsa"},{"a":["abc"],"o":"cba"}]),
S("c_prime","c","prime.c","C11 CLI. Inteiro, imprima PRIME ou NOT PRIME.",[{"a":["17"],"o":"PRIME"},{"a":["21"],"o":"NOT PRIME"}]),
S("c_restock","c","restock.c","C11 CLI. Args stock:min, conte stock<min, imprima reorder=N.",[{"a":["2:5","8:2","1:3"],"o":"reorder=2"},{"a":["3:3"],"o":"reorder=0"}]),
S("c_checksum","c","checksum.c","C11 CLI. String argv[1], some valores ASCII dos bytes, imprima checksum=N.",[{"a":["ABC"],"o":"checksum=198"},{"a":["A"],"o":"checksum=65"}]),

S("cpp_unique","cpp","unique.cpp","C++17 CLI. Inteiros, ordene, unique, imprima por vírgula.",[{"a":["3","1","3","2"],"o":"1,2,3"},{"a":["5","5"],"o":"5"}]),
S("cpp_wordfreq","cpp","wordfreq.cpp","C++17 CLI. Palavras args, conte ignorando caixa, mais frequente; empate alfabético. Imprima word=N.",[{"a":["Code","astra","code"],"o":"code=2"},{"a":["z","b","z","b"],"o":"b=2"}]),
S("cpp_fleet","cpp","fleet.cpp","C++17 CLI. Mileages inteiros como args, some e imprima fleet_km=N.",[{"a":["100","50","25"],"o":"fleet_km=175"},{"a":["0"],"o":"fleet_km=0"}]),
S("cpp_queue","cpp","queue.cpp","C++17 CLI. Itens args, use std::queue, retire e imprima por >.",[{"a":["a","b","c"],"o":"a>b>c"},{"a":["x"],"o":"x"}]),
S("cpp_route","cpp","route.cpp","C++17 CLI. Distâncias decimais args, imprima distance=X.XX.",[{"a":["1.5","2.25"],"o":"distance=3.75"},{"a":["10"],"o":"distance=10.00"}]),
S("cpp_grade","cpp","grade.cpp","C++17 CLI. Notas decimais; média>=7 PASS, senão FAIL. average=X.XX result=PASS|FAIL.",[{"a":["8","6"],"o":"average=7.00 result=PASS"},{"a":["5","6"],"o":"average=5.50 result=FAIL"}]),

S("rust_sum","rust","sum.rs","Rust CLI std. Some args inteiros, imprima sum=N.",[{"a":["1","2","3"],"o":"sum=6"},{"a":["-2","5"],"o":"sum=3"}]),
S("rust_fleet","rust","fleet.rs","Rust CLI. Args active/maintenance, conte e imprima active=N maintenance=N.",[{"a":["active","maintenance","active"],"o":"active=2 maintenance=1"},{"a":["active"],"o":"active=1 maintenance=0"}]),
S("rust_unique","rust","unique.rs","Rust CLI. Inteiros, remova duplicados, ordene e imprima por vírgula.",[{"a":["3","1","3","2"],"o":"1,2,3"},{"a":["9","9"],"o":"9"}]),
S("rust_restock","rust","restock.rs","Rust CLI. Args stock:min, conte stock<min, imprima reorder=N.",[{"a":["2:5","8:2","1:3"],"o":"reorder=2"},{"a":["5:5"],"o":"reorder=0"}]),
S("rust_kv","rust","kv.rs","Rust CLI. Args key=value, ordene por key e imprima por vírgula.",[{"a":["b=2","a=1"],"o":"a=1,b=2"},{"a":["x=ok"],"o":"x=ok"}]),
S("rust_temp","rust","temp.rs","Rust CLI. Celsius decimal, imprima fahrenheit=X.XX.",[{"a":["0"],"o":"fahrenheit=32.00"},{"a":["100"],"o":"fahrenheit=212.00"}]),
]
assert len(SPECS)==50, len(SPECS)

LABEL={"python":"Python 3","javascript":"Node.js JavaScript","bash":"Bash","c":"C11","cpp":"C++17","rust":"Rust"}

def clean_code(text):
    text=text.strip()
    fence=chr(96)*3
    if fence in text:
        parts=text.split(fence)
        if len(parts)>=3:
            body=parts[1]
            lines=body.splitlines()
            if lines and re.fullmatch(r"[A-Za-z0-9_+#.-]+",lines[0].strip()):
                lines=lines[1:]
            return "\n".join(lines).strip()+"\n"
    lines=text.splitlines()
    if lines and lines[0].lower().startswith(("aqui está","aqui esta","segue o código","segue o codigo")): lines=lines[1:]
    return "\n".join(lines).strip()+"\n"

def generate(spec,previous="",failure=""):
    hints={
        "python":"Em Python, argumentos do usuário começam em sys.argv[1].",
        "javascript":"Em Node.js, argumentos do usuário são process.argv.slice(2).",
        "bash":"Em Bash, argumentos do usuário são $1, $2... ou $@.",
        "c":"Em C, argv[0] é o executável e os dados começam em argv[1].",
        "cpp":"Em C++, argv[0] é o executável e os dados começam em argv[1].",
        "rust":"Em Rust, std::env::args() inclui o executável primeiro; ignore-o.",
    }
    rows=[]
    for idx,c in enumerate(spec.cases,1):
        argv=json.dumps(c.get("a",[]),ensure_ascii=False)
        stdin=json.dumps(c.get("i",""),ensure_ascii=False)
        stdout=json.dumps(c["o"],ensure_ascii=False)
        rows.append(f"Exemplo {idx}: argv do usuário = {argv}; stdin = {stdin}; stdout EXATO = {stdout}")
    examples="\n".join(rows)
    prompt=f"""Crie um programa completo em {LABEL[spec.lang]}.
Arquivo: {spec.filename}
Requisito funcional: {spec.requirement}
{hints[spec.lang]}
ATENÇÃO: se um único argumento contém vírgulas ou dois-pontos, ele continua sendo UM argumento; o programa deve parsear o conteúdo desse argumento conforme o requisito.
Casos reais obrigatórios:
{examples}
Sem dependências externas. Use somente biblioteca padrão. Implemente a lógica geral; não hardcode as respostas dos exemplos. A saída deve bater exatamente.
RETORNE SOMENTE O CÓDIGO-FONTE, sem markdown e sem explicações."""
    if previous:
        prompt+=f"""
Código anterior:
{previous}
Falha real observada:
{failure}
Corrija exatamente a causa mantendo todos os requisitos e exemplos. Retorne somente o código completo."""
    return clean_code(client.chat(prompt,system=CODE_SYSTEM,num_ctx=2048,num_predict=320,temperature=0.01,think=False))

def save(spec,code,overwrite=False):
    p=ROOT/spec.filename
    action="write_file" if overwrite or p.exists() else "create_text_file"
    r=files.execute(action,{"path":str(p),"content":code})
    if not r.ok: raise RuntimeError(r.message)
    return p

def cmd_for(spec,p):
    stem=Path(spec.filename).stem
    if spec.lang=="python": return ["/usr/bin/python3","-m","py_compile",str(p)],[ "/usr/bin/python3",str(p)]
    if spec.lang=="javascript":
        n=shutil.which("node"); return [n,"--check",str(p)],[n,str(p)]
    if spec.lang=="bash": return ["/usr/bin/bash","-n",str(p)],[ "/usr/bin/bash",str(p)]
    if spec.lang=="c":
        out=BIN/stem; return ["/usr/bin/gcc","-std=c11","-Wall","-Wextra","-O0",str(p),"-o",str(out)],[str(out)]
    if spec.lang=="cpp":
        out=BIN/stem; return ["/usr/bin/g++","-std=c++17","-Wall","-Wextra","-O0",str(p),"-o",str(out)],[str(out)]
    if spec.lang=="rust":
        out=BIN/stem; return [shutil.which("rustc"),"--edition=2021",str(p),"-o",str(out)],[str(out)]
    raise ValueError(spec.lang)

def run(cmd,stdin="",timeout=20):
    p=subprocess.run(cmd,input=stdin,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    return p.returncode,p.stdout.strip(),p.stderr.strip()

def validate(spec,p):
    check,base=cmd_for(spec,p); rc,out,err=run(check)
    if rc: return False,f"compile/syntax rc={rc} stdout={out!r} stderr={err!r}"
    details=[]
    for idx,c in enumerate(spec.cases,1):
        rc,out,err=run(base+c.get("a",[]),c.get("i",""),8)
        details.append({"case":idx,"rc":rc,"out":out,"expected":c["o"],"err":err})
        if rc or out!=c["o"]: return False,f"case {idx} rc={rc} expected={c['o']!r} got={out!r} stderr={err!r}"
    return True,details

results=[]; start=time.perf_counter()
limit=int(__import__("os").environ.get("ASTRA_EVAL_LIMIT","50"))
client.preload()
print(f"START programs={min(limit,len(SPECS))} model=qwen2.5-coder:3b root={ROOT}",flush=True)
for i,spec in enumerate(SPECS[:limit],1):
    t=time.perf_counter(); code=""; failure=""; ok=False
    rec={"index":i,"name":spec.name,"lang":spec.lang,"file":spec.filename,"attempts":0}
    for attempt in (1,2):
        rec["attempts"]=attempt
        try:
            newcode=generate(spec,code if attempt==2 else "",failure if attempt==2 else "")
            code=newcode; p=save(spec,code,overwrite=(attempt==2))
            ok,detail=validate(spec,p)
            if ok: rec["detail"]=detail; break
            failure=str(detail)
        except Exception as e:
            failure=repr(e); ok=False
    rec.update(ok=ok,failure="" if ok else failure,seconds=round(time.perf_counter()-t,3)); results.append(rec)
    print(f"[{i:02d}/50] {spec.lang:<10} {spec.name:<20} {'PASS' if ok else 'FAIL'} attempts={rec['attempts']} time={rec['seconds']}s",flush=True)
    if not ok: print("  -> "+failure.replace("\n"," | ")[:500],flush=True)

bats=[
("fleet_status.bat","Receba statuses nos argumentos e conte active e maintenance; imprima active=N maintenance=N."),
("backup_name.bat","Receba caminho em %1 e imprima nome seguido de .bak."),
("disk_level.bat","Receba percentual em %1 e imprima OK, WARN ou CRIT nos limites 70/90."),
("sum.bat","Some até quatro args inteiros com set /a e imprima sum=N."),
("env_report.bat","Imprima user=%USERNAME% e computer=%COMPUTERNAME% numa linha."),
]
batch=[]
for fn,req in (bats if limit >= 50 else []):
    raw=client.chat(f"Crie Windows batch cmd.exe. Arquivo {fn}. Requisito: {req} Comece com @echo off. Não use PowerShell. Retorne só o .bat.",system=AstraBrain._system(),num_ctx=1536,num_predict=240,temperature=0.05,think=False)
    code=clean_code(raw); p=ROOT/fn
    rr=files.execute("write_file" if p.exists() else "create_text_file",{"path":str(p),"content":code})
    static=bool(rr.ok and re.search(r"(?im)^@echo off\s*$",code) and not code.lstrip().startswith("#!"))
    batch.append({"file":fn,"generated":bool(rr.ok),"static_ok":static,"runtime":"SKIPPED_NO_CMD_WINE"})
    print(f"[BAT] {fn:<18} {'STATIC_OK' if static else 'STATIC_FAIL'} runtime=SKIPPED(no cmd/wine)",flush=True)

summary={"programs_total":len(results),"programs_passed":sum(r["ok"] for r in results),"programs_failed":sum(not r["ok"] for r in results),"first_try_passed":sum(r["ok"] and r["attempts"]==1 for r in results),"repaired_passed":sum(r["ok"] and r["attempts"]==2 for r in results),"batch_generated":len(batch),"batch_static_ok":sum(x["static_ok"] for x in batch),"elapsed_seconds":round(time.perf_counter()-start,3)}
(ROOT/"results.json").write_text(json.dumps({"summary":summary,"results":results,"batch":batch},ensure_ascii=False,indent=2),encoding="utf-8")
print("SUMMARY "+json.dumps(summary,ensure_ascii=False),flush=True)
