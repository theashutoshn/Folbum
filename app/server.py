import base64
import hmac
import json
import os
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .engine import DEMO_ASSETS, IntegrationError, PhotosClient, plan

BASE=pathlib.Path(__file__).resolve().parent.parent
DATA=pathlib.Path(os.environ.get('DATA_DIR','/app/data'))
DATA.mkdir(parents=True,exist_ok=True)
CONFIG=DATA/'config.json'
STATE=DATA/'sync_state.json'
HISTORY=DATA/'history.json'
CREDENTIALS=DATA/'credentials.json'
CONNECTION=DATA/'connection.json'
MODE=os.environ.get('ZIMA_MODE','demo').lower()
PASSWORD=os.environ.get('APP_PASSWORD','')
ALLOW_WRITE=os.environ.get('ENABLE_LIVE_WRITES','false').lower()=='true'
API_URL=os.environ.get('ZIMA_URL','')
LOCK=threading.RLock()
DEFAULT={'root':'','interval_minutes':0}
DEMO_ALBUMS=[]
DEMO_MEMBERS={}
DEMO_STATE=DATA/'demo_albums.json'


def read_json(path,default):
    try:
        with path.open(encoding='utf-8') as f:return json.load(f)
    except FileNotFoundError:return default

def write_json(path,data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,path)

def init_demo():
    saved=read_json(DEMO_STATE,{'albums':[],'members':{}})
    DEMO_ALBUMS.extend(saved.get('albums',[]))
    DEMO_MEMBERS.update({k:set(v) for k,v in saved.get('members',{}).items()})

def save_demo():
    write_json(DEMO_STATE,{'albums':DEMO_ALBUMS,'members':{k:sorted(v) for k,v in DEMO_MEMBERS.items()}})

if MODE=='demo':init_demo()

def config():
    saved=read_json(CONFIG,{})
    return {key:saved.get(key,default) for key,default in DEFAULT.items()}

def mapping_key(root,folder):
    return 'auto|'+root+'|'+folder

def get_client():
    if MODE!='live':return None
    endpoint=read_json(CONNECTION,{}).get('url') or API_URL
    if not endpoint or not CREDENTIALS.is_file():raise IntegrationError('Connect to ZimaOS Photos first')
    return PhotosClient(endpoint,str(CREDENTIALS))

def connect(payload):
    if MODE!='live':raise IntegrationError('Connection setup is only available in live mode')
    url=str(payload.get('url','')).strip().rstrip('/')
    username=str(payload.get('username','')).strip()
    password=payload.get('password','')
    if not isinstance(password,str):raise ValueError('Invalid password')
    tokens=PhotosClient.login(url,username,password)
    # Validate Photos access before replacing the saved connection.
    import urllib.request
    probe=urllib.request.Request(url+'/v2/photos/sources',headers={
        'Authorization':tokens['access_token'],'Accept':'application/json'})
    try:
        with urllib.request.urlopen(probe,timeout=20) as response:
            if response.status!=200:raise IntegrationError('Photos API access was rejected')
    except (OSError,ValueError) as exc:
        raise IntegrationError('Could not validate Photos access') from exc
    with LOCK:
        write_json(CREDENTIALS,tokens)
        write_json(CONNECTION,{'url':url})
    return {'connected':True,'url':url}

def fetch():
    if MODE=='demo':return DEMO_ASSETS[:],DEMO_ALBUMS[:],None
    client=get_client()
    return client.gallery(),client.albums(),client

def snapshot():
    assets,albums,client=fetch()
    cfg=config();all_mappings=read_json(STATE,{})
    mapping={key.split('|',2)[2]:value for key,value in all_mappings.items()
             if key.startswith('auto|'+cfg['root']+'|')}
    rows=plan(assets,albums,cfg,mapping) if cfg.get('root') else []
    for row in rows:
        members=(client.members(row['album_id']) if client else DEMO_MEMBERS.get(row['album_id'],set())) if row['album_id'] else set()
        row['missing']=len(set(row['asset_ids'])-set(members))
        row.pop('asset_ids',None)
    return {'rows':rows,'asset_count':len(assets),'album_count':len(albums),'configuration':cfg}

def sync():
    if MODE=='live' and not ALLOW_WRITE:
        raise IntegrationError('Live writes disabled: set ENABLE_LIVE_WRITES=true only after reviewing a dry run')
    with LOCK:
        assets,albums,client=fetch();cfg=config();all_mappings=read_json(STATE,{})
        if not cfg.get('root'):raise IntegrationError('Choose a Photos source first')
        mapping={key.split('|',2)[2]:value for key,value in all_mappings.items()
                 if key.startswith('auto|'+cfg['root']+'|')}
        rows=plan(assets,albums,cfg,mapping)
        made=0;added=0
        for row in rows:
            identifier=row['album_id']
            if not identifier:
                if client:
                    identifier=client.create_album(row['album'])
                else:
                    identifier='demo-'+str(len(DEMO_ALBUMS)+1)
                    DEMO_ALBUMS.append({'id':identifier,'name':row['album']})
                    DEMO_MEMBERS[identifier]=set()
                made+=1
                all_mappings[mapping_key(cfg['root'],row['folder'])]=identifier
                write_json(STATE,all_mappings)
                if MODE=='demo':save_demo()
            current=client.members(identifier) if client else DEMO_MEMBERS.setdefault(identifier,set())
            missing=sorted(set(row['asset_ids'])-set(current))
            if missing:
                if client:client.add_members(identifier,missing)
                else:DEMO_MEMBERS[identifier].update(missing)
            added+=len(missing)
            all_mappings[mapping_key(cfg['root'],row['folder'])]=identifier
            write_json(STATE,all_mappings)
        if MODE=='demo':save_demo()
        result={'time':int(time.time()),'created':made,'added':added,'mode':MODE,'success':True}
        history=read_json(HISTORY,[])
        write_json(HISTORY,([result]+history)[:40]);return result

def update_config(payload):
    if not isinstance(payload,dict):raise ValueError('Expected JSON object')
    old=config()
    root=payload.get('root',old['root'])
    if not isinstance(root,str) or (root and (not root.startswith('/') or '..' in root.split('/') or '\\' in root)):
        raise ValueError('Invalid gallery path; use the API-visible /media/... prefix')
    if MODE=='live' and root:
        paths={source['path'].rstrip('/') for source in get_client().sources() if source['available']}
        if root.rstrip('/') not in paths:raise ValueError('Choose an available Photos source')
    iv=payload.get('interval_minutes',old['interval_minutes'])
    if type(iv) is not int or iv not in (0,5,10,15,30,60,120,360,1440):
        raise ValueError('Choose a supported interval')
    new={'root':root.rstrip('/'),'interval_minutes':iv}
    with LOCK:write_json(CONFIG,new)
    return new

class Handler(BaseHTTPRequestHandler):
    def _send(self,status,obj):
        data=json.dumps(obj).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(data)
    def _authorized(self):
        if not PASSWORD:return True
        auth=self.headers.get('Authorization','')
        if not auth.startswith('Basic '):return False
        try:decoded=base64.b64decode(auth[6:]).decode()
        except Exception:return False
        username,_,password=decoded.partition(':')
        return hmac.compare_digest(username,'admin') and hmac.compare_digest(password,PASSWORD)
    def _dispatch(self):
        if self.path=='/api/health':return self._send(200,{'ok':True,'mode':MODE})
        if not self._authorized():
            self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Zima Album Sync"');self.send_header('Content-Length','0');self.end_headers();return
        if self.command=='POST':
            origin=self.headers.get('Origin')
            if origin:
                from urllib.parse import urlsplit
                expected=urlsplit('http://'+self.headers.get('Host',''))
                actual=urlsplit(origin)
                if actual.netloc!=expected.netloc or actual.scheme not in ('http','https'):
                    return self._send(403,{'error':'Cross-origin request blocked'})
        try:
            if self.command=='GET':
                if self.path=='/api/status':return self._send(200,{'mode':MODE,'live_writes_enabled':ALLOW_WRITE,'connected':MODE=='demo' or CREDENTIALS.is_file(),'url':read_json(CONNECTION,{}).get('url',API_URL),'configuration':config(),'history':read_json(HISTORY,[])[:10]})
                if self.path=='/api/sources':return self._send(200,{'items':get_client().sources()} if MODE=='live' else {'items':[{'id':'demo','path':'/media/HDD-Storage/Gallery','available':True,'status':'demo'}]})
                if self.path=='/api/preview':return self._send(200,snapshot())
                if self.path=='/api/history':return self._send(200,read_json(HISTORY,[]))
                if self.path=='/' or self.path=='/index.html':return self._static('index.html','text/html; charset=utf-8')
                if self.path=='/app.js':return self._static('app.js','application/javascript; charset=utf-8')
                if self.path=='/style.css':return self._static('style.css','text/css; charset=utf-8')
                return self._send(404,{'error':'Not found'})
            if self.command=='POST':
                length=int(self.headers.get('Content-Length','0'))
                if length>1048576: return self._send(413,{'error':'Payload too large'})
                raw=self.rfile.read(length)
                payload=json.loads(raw or b'{}')
                if self.path=='/api/connect':return self._send(200,connect(payload))
                if self.path=='/api/config':return self._send(200,update_config(payload))
                if self.path=='/api/sync':
                    if payload.get('confirm')!='SYNC':raise ValueError('Explicit SYNC confirmation required')
                    return self._send(200,sync())
                return self._send(404,{'error':'Not found'})
            return self._send(405,{'error':'Method not allowed'})
        except (IntegrationError,ValueError,KeyError,TypeError,OverflowError) as exc:
            return self._send(400,{'error':str(exc)})
        except Exception:
            self.log_error('Unhandled error on %s',self.path)
            return self._send(500,{'error':'Unexpected server error; see container logs'})
    def _static(self,filename,mimetype):
        data=(BASE/'static'/filename).read_bytes()
        self.send_response(200);self.send_header('Content-Type',mimetype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_GET(self):self._dispatch()
    def do_POST(self):self._dispatch()
    def log_message(self,format,*args):print('%s %s'%(self.address_string(),format%args),flush=True)

def scheduler():
    last=0
    while True:
        time.sleep(30)
        interval=config()['interval_minutes']
        if interval and time.monotonic()-last>=interval*60:
            last=time.monotonic()
            if MODE=='live' and not ALLOW_WRITE:continue
            try:sync()
            except Exception as exc:print('Scheduled sync failed: '+str(exc),flush=True)

if __name__=='__main__':
    if MODE not in ('demo','live'):raise SystemExit('ZIMA_MODE must be demo or live')
    if not PASSWORD or PASSWORD in ('REPLACE_WITH_STRONG_UNIQUE_PASSWORD','CHANGE_THIS_BEFORE_INSTALL'):
        raise SystemExit('Set a unique APP_PASSWORD in .env before starting')
    threading.Thread(target=scheduler,daemon=True).start()
    port=int(os.environ.get('PORT','8765'))
    print('Starting Zima Album Sync in '+MODE+' mode on '+str(port),flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
