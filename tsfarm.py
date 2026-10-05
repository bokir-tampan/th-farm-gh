#!/usr/bin/env python3
"""tsfarm.py — farm akun New-API di host ber-Turnstile dari GH runner.
Pakai Camoufox (Firefox) — managed Turnstile auto-issue token di JS context nyata.
Arg: base_url  count  out_file
Output: JSONL tiap akun {host,user,pass,uid,quota,key,verdict}"""
import asyncio, json, random, string, sys, os, time

BASE = sys.argv[1].rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OUT = sys.argv[3] if len(sys.argv) > 3 else "tsfarm.jsonl"
HOST = BASE.split("//")[1]
fo = open(OUT, "a")


def rand(n, alpha=string.ascii_lowercase + string.digits):
    return "".join(random.choices(alpha, k=n))


async def do_account(cam, idx):
    tag = rand(9)
    user = "t" + tag
    pw = "T" + rand(11, string.ascii_letters + string.digits)
    email = f"{tag}@gmail.com"
    page = await cam.new_page()
    # bersihkan + buka halaman sign-up
    for path in ("/sign-up", "/register", "/#/register", "/console"):
        try:
            await page.goto(BASE + path, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            continue
        await asyncio.sleep(3)
        # cari form: isi username/password bila ada
        try:
            inputs = await page.eval_on_selector_all(
                "input",
                "els=>els.map(e=>({name:e.name,type:e.type,id:e.id,ph:e.placeholder,vis:e.offsetParent!==null}))")
        except Exception:
            inputs = []
        has_up = any((i.get("name") or "").lower() in ("username", "user") for i in inputs)
        if has_up or any(i.get("type") == "password" for i in inputs):
            break
    # isi field dengan keyboard (React butuh event asli)
    async def fill(sel_names, val):
        for nm in sel_names:
            try:
                el = await page.query_selector(f'input[name="{nm}"]') or await page.query_selector(f'#{nm}')
                if el:
                    await el.click()
                    await el.fill("")
                    await page.keyboard.type(val, delay=30)
                    return True
            except Exception:
                continue
        return False
    if email:
        await fill(["email", "Email"], email)
    await fill(["username", "user", "name"], user)
    await fill(["password", "Password"], pw)
    await fill(["password2", "confirmPassword", "confirm_password"], pw)
    # tunggu Turnstile token
    tok = None
    for _ in range(30):
        try:
            tok = await page.evaluate("()=>{const e=document.querySelector('[name=cf-turnstile-response]');return e?e.value:''}")
        except Exception:
            tok = ""
        if tok and len(tok) > 100:
            break
        # klik widget kalau belum ada token (managed mode butuh interaksi)
        try:
            fr = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
            if fr:
                box = await fr.bounding_box()
                if box:
                    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=6)
                    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        except Exception:
            pass
        await asyncio.sleep(2)
    # submit form register (same-origin fetch) — pakai token bila ada
    res = await page.evaluate(
        """async ([u,p,e,tok])=>{
            const body={username:u,password:p,password2:p,email:e,verification_code:''};
            if(tok){body['cf-turnstile-response']=tok;body['turnstile_token']=tok;body['token']=tok;}
            const r=await fetch('/api/user/register',{method:'POST',credentials:'include',
                headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            return {status:r.status, text:(await r.text()).slice(0,300)};
        }""", [user, pw, email, tok or ""])
    reg = res.get("text", "")
    if not (res.get("status") == 200 and '"success":true' in reg):
        await page.close()
        return {"host": BASE, "user": user, "pass": pw, "verdict": "REG_FAIL",
                "ts": bool(tok and len(tok) > 100), "body": reg[:120]}
    # login + ambil key via fetch same-origin
    lr = await page.evaluate(
        """async ([u,p])=>{
            const r=await fetch('/api/user/login',{method:'POST',credentials:'include',
                headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
            const j=await r.json();
            const uid=(j.data&&(j.data.id||(j.data.user&&j.data.user.id)))||null;
            return {uid, tok:(j.data&&j.data.access_token)||null};
        }""", [user, pw])
    uid = lr.get("uid")
    hd = {"New-Api-User": str(uid), "New-API-User": str(uid)}
    if lr.get("tok"):
        hd["Authorization"] = "Bearer " + lr["tok"]
    sd = await page.evaluate(
        """async ([hd])=>{const r=await fetch('/api/user/self',{credentials:'include',headers:hd});
            try{return await r.json()}catch(e){return {}}}""", [hd])
    quota = ((sd or {}).get("data") or {}).get("quota")
    key = await page.evaluate(
        """async ([hd])=>{
            const lr=await fetch('/api/token/?p=0&size=20',{credentials:'include',headers:hd});
            const lj=await lr.json();
            let items=(lj.data&&(lj.data.items||lj.data))||[];
            if(!items.length){
                await fetch('/api/token/',{method:'POST',credentials:'include',
                    headers:{...hd,'Content-Type':'application/json'},
                    body:JSON.stringify({name:'t1',remain_quota:500000000,unlimited_quota:true,expired_time:-1,model_limits_enabled:false,group:''})});
                const l2=await fetch('/api/token/?p=0&size=20',{credentials:'include',headers:hd});
                const j2=await l2.json();items=(j2.data&&(j2.data.items||j2.data))||[];
            }
            if(!items.length)return null;
            const tid=items[items.length-1].id;
            const kr=await fetch('/api/token/'+tid+'/key',{method:'POST',credentials:'include',headers:hd});
            const kj=await kr.json();
            return (kj.data&&kj.data.key)||(typeof kj.data==='string'?kj.data:null);
        }""", [hd])
    await page.close()
    rec = {"host": BASE, "user": user, "pass": pw, "uid": uid, "quota": quota, "key": key,
           "verdict": "KEY" if key else "NO_KEY"}
    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    return rec


async def main():
    from camoufox.async_api import AsyncCamoufox
    for i in range(N):
        try:
            async with AsyncCamoufox(headless=True, humanize=True) as cam:
                r = await do_account(cam, i)
            print(f"[{i}] {r.get('verdict')} q={r.get('quota')} key={'Y' if r.get('key') else '-'} "
                  f"ts={r.get('ts')} {r.get('body','')[:60]}", flush=True)
        except Exception as e:
            print(f"[{i}] EXC {str(e)[:100]}", flush=True)

asyncio.run(main())
