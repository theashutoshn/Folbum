import hashlib
import hmac
import json
import os
import pathlib
import secrets
import threading
import time
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .engine import DEMO_ASSETS, IntegrationError, PhotosClient, TOKEN_REFRESH_LOCK, plan, valid_base_url
from .reconcile import compare_paths, filesystem_files, indexed_files

BASE=pathlib.Path(__file__).resolve().parent.parent
DATA=pathlib.Path(os.environ.get('DATA_DIR','/app/data'))
DATA.mkdir(parents=True,exist_ok=True)
CONFIG=DATA/'config.json'
STATE=DATA/'sync_state.json'
HISTORY=DATA/'history.json'
CREDENTIALS=DATA/'credentials.json'
CONNECTION=DATA/'connection.json'
SESSIONS=DATA/'sessions.json'
MODE=os.environ.get('ZIMA_MODE','demo').lower()
APP_TIMEZONE=os.environ.get('APP_TIMEZONE','Asia/Kolkata').strip() or 'Asia/Kolkata'
PASSWORD=os.environ.get('APP_PASSWORD','')
SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE','false').lower()=='true'
SESSION_TTL=12*60*60
REMEMBERED_SESSION_TTL=30*24*60*60
ALLOW_WRITE=os.environ.get('ENABLE_LIVE_WRITES','false').lower()=='true'
DISK_GALLERY_ROOT=os.environ.get('DISK_GALLERY_ROOT','')
DISK_SOURCE_PATH=os.environ.get('DISK_SOURCE_PATH','').rstrip('/')
LOCK=threading.RLock()
LOGIN_FAILURES={}
TEMP_CREDENTIALS=DATA/'volatile_credentials.json'
TEMP_CREDENTIALS.unlink(missing_ok=True)
TEMP_CONNECTION=None
TEMP_NAME=None
TEMP_ACTIVE=False
DEFAULT={'root':'','interval_minutes':0}
DEMO_ALBUMS=[]
DEMO_MEMBERS={}
DEMO_STATE=DATA/'demo_albums.json'


def local_time(value=None):
    instant=datetime.now(ZoneInfo(APP_TIMEZONE)) if value is None else datetime.fromtimestamp(value,ZoneInfo(APP_TIMEZONE))
    return instant.isoformat(timespec='seconds')


def log_event(message):
    print(local_time()+' '+message,flush=True)


def read_json(path,default):
    try:
        with path.open(encoding='utf-8') as f:return json.load(f)
    except FileNotFoundError:return default

def write_json(path,data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,path)

def session_key(token):
    return hmac.new(PASSWORD.encode('utf-8'),token.encode('utf-8'),hashlib.sha256).hexdigest()

def create_session(remember=False):
    token=secrets.token_urlsafe(32)
    now=int(time.time())
    ttl=REMEMBERED_SESSION_TTL if remember else SESSION_TTL
    with LOCK:
        saved=read_json(SESSIONS,{})
        active={key:expiry for key,expiry in saved.items()
                if isinstance(expiry,(int,float)) and expiry>now}
        active[session_key(token)]=now+ttl
        write_json(SESSIONS,active)
    return token,ttl

def valid_session(token):
    if not token or len(token)>128:return False
    expiry=read_json(SESSIONS,{}).get(session_key(token),0)
    return isinstance(expiry,(int,float)) and expiry>time.time()

def revoke_session(token):
    if not token or len(token)>128:return
    with LOCK:
        saved=read_json(SESSIONS,{})
        if saved.pop(session_key(token),None) is not None:
            write_json(SESSIONS,saved)

def cookie_header(token='',clear=False,ttl=SESSION_TTL):
    value=f'zima_session={token}; Path=/; HttpOnly; SameSite=Strict'
    value+= '; Max-Age=0' if clear else f'; Max-Age={ttl}'
    if SESSION_COOKIE_SECURE:value+='; Secure'
    return value

def login_allowed(address):
    now=time.monotonic()
    with LOCK:
        recent=[when for when in LOGIN_FAILURES.get(address,[]) if now-when<60]
        if recent:LOGIN_FAILURES[address]=recent
        else:LOGIN_FAILURES.pop(address,None)
        return len(recent)<5

def record_login_failure(address):
    with LOCK:LOGIN_FAILURES.setdefault(address,[]).append(time.monotonic())

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

def nas_namespace(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]


def mapping_prefix(root):
    if MODE=='live':
        info=connection_info()
        saved=read_json(CONNECTION,{})
        if info['url'] and (TEMP_CONNECTION is not None or saved.get('state_namespace')):
            return 'auto|nas:'+nas_namespace(info['url'])+'|'+root+'|'
    return 'auto|'+root+'|'


def mapping_key(root,folder):
    return mapping_prefix(root)+folder

def connection_info():
    if TEMP_CONNECTION is not None:
        return {'url':TEMP_CONNECTION,'name':TEMP_NAME or urlsplit(TEMP_CONNECTION).hostname,
                'active':TEMP_ACTIVE,'connected':TEMP_ACTIVE and TEMP_CREDENTIALS.is_file(),
                'remember_connection':False}
    saved=read_json(CONNECTION,{})
    url=saved.get('url','')
    active=saved.get('active',True)
    connected=active and CREDENTIALS.is_file() and bool(url)
    return {'url':url,'name':saved.get('name') or (urlsplit(url).hostname if url else ''),
            'active':active,'connected':connected,'remember_connection':True}

def get_client():
    if MODE!='live':return None
    info=connection_info()
    if not info['connected']:raise IntegrationError('Connect to ZimaOS Photos first')
    return PhotosClient(info['url'],str(TEMP_CREDENTIALS if TEMP_CONNECTION is not None else CREDENTIALS))

def connect(payload):
    global TEMP_CONNECTION,TEMP_NAME,TEMP_ACTIVE
    if MODE!='live':raise IntegrationError('Connection setup is only available in live mode')
    if not isinstance(payload,dict):raise ValueError('Expected connection details')
    remember=payload.get('remember_connection',True)
    if type(remember) is not bool:raise ValueError('Invalid remember connection setting')
    url=str(payload.get('url','')).strip().rstrip('/')
    if url and '://' not in url:url='http://'+url
    if not valid_base_url(url):raise ValueError('Enter a valid NAS IP address or URL')
    name=payload.get('name','')
    if not isinstance(name,str) or len(name)>80 or any(ord(char)<32 for char in name):
        raise ValueError('Invalid NAS name')
    name=name.strip() or urlsplit(url).hostname
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
        with TOKEN_REFRESH_LOCK:
            old_url=connection_info()['url']
            old_connection=read_json(CONNECTION,{})
            if TEMP_CONNECTION is None and old_url and not old_connection.get('state_namespace'):
                mappings=read_json(STATE,{})
                migrated=dict(mappings)
                for key,value in mappings.items():
                    if key.startswith('auto|') and not key.startswith('auto|nas:'):
                        migrated['auto|nas:'+nas_namespace(old_url)+'|'+key[5:]]=value
                if migrated!=mappings:write_json(STATE,migrated)
            if old_url and old_url!=url:
                write_json(CONFIG,{'root':'','interval_minutes':0})
            if remember:
                write_json(CREDENTIALS,tokens)
                write_json(CONNECTION,{'url':url,'name':name,'state_namespace':True,'active':True})
                TEMP_CONNECTION=None
                TEMP_NAME=None
                TEMP_ACTIVE=False
            else:
                write_json(TEMP_CREDENTIALS,tokens)
                TEMP_CONNECTION=url
                TEMP_NAME=name
                TEMP_ACTIVE=True
                CREDENTIALS.unlink(missing_ok=True)
                CONNECTION.unlink(missing_ok=True)
    return {'connected':True,'url':url,'name':name,'remember_connection':remember}


def disconnect_connection():
    global TEMP_ACTIVE
    if MODE!='live':raise IntegrationError('Connection controls are only available in live mode')
    with LOCK:
        info=connection_info()
        if not info['url']:raise IntegrationError('No NAS connection to disconnect')
        if TEMP_CONNECTION is not None:TEMP_ACTIVE=False
        else:
            saved=read_json(CONNECTION,{})
            saved['active']=False
            write_json(CONNECTION,saved)
    return {'connected':False,'url':info['url']}


def reconnect_connection():
    global TEMP_ACTIVE
    if MODE!='live':raise IntegrationError('Connection controls are only available in live mode')
    with LOCK:
        info=connection_info()
        if not info['url']:raise IntegrationError('No saved NAS connection; use + to add one')
        path=TEMP_CREDENTIALS if TEMP_CONNECTION is not None else CREDENTIALS
        client=PhotosClient(info['url'],str(path))
        client.sources()  # Reuse saved tokens only after an authenticated Photos API check.
        if TEMP_CONNECTION is not None:TEMP_ACTIVE=True
        else:
            saved=read_json(CONNECTION,{})
            saved['active']=True
            write_json(CONNECTION,saved)
    return {'connected':True,'url':info['url']}


def delete_connection():
    global TEMP_CONNECTION,TEMP_NAME,TEMP_ACTIVE
    if MODE!='live':raise IntegrationError('Connection controls are only available in live mode')
    with LOCK:
        with TOKEN_REFRESH_LOCK:
            TEMP_CREDENTIALS.unlink(missing_ok=True)
            CREDENTIALS.unlink(missing_ok=True)
            CONNECTION.unlink(missing_ok=True)
            TEMP_CONNECTION=None
            TEMP_NAME=None
            TEMP_ACTIVE=False
            write_json(CONFIG,{'root':'','interval_minutes':0})
    return {'deleted':True}

def fetch():
    if MODE=='demo':return DEMO_ASSETS[:],DEMO_ALBUMS[:],None
    client=get_client()
    return client.gallery(),client.albums(),client

def disk_comparison(assets, source):
    if not source:
        return {'status':'no_source'}
    indexed=indexed_files(assets,source)
    if MODE=='demo':
        return compare_paths(indexed | {'Unindexed/example-photo.jpg'},indexed)
    if not DISK_GALLERY_ROOT or not DISK_SOURCE_PATH:
        return {'status':'not_configured'}
    if source.rstrip('/')!=DISK_SOURCE_PATH:
        return {'status':'source_mismatch'}
    try:
        disk=filesystem_files(DISK_GALLERY_ROOT)
    except OSError:
        return {'status':'unavailable'}
    return compare_paths(disk,indexed)

def snapshot():
    assets,albums,client=fetch()
    cfg=config();all_mappings=read_json(STATE,{})
    prefix=mapping_prefix(cfg['root'])
    mapping={key[len(prefix):]:value for key,value in all_mappings.items()
             if key.startswith(prefix)}
    rows=plan(assets,albums,cfg,mapping) if cfg.get('root') else []
    for row in rows:
        members=(client.members(row['album_id']) if client else DEMO_MEMBERS.get(row['album_id'],set())) if row['album_id'] else set()
        row['missing']=len(set(row['asset_ids'])-set(members))
        row.pop('asset_ids',None)
    return {'rows':rows,'asset_count':len(assets),'album_count':len(albums),
            'configuration':cfg,'disk_comparison':disk_comparison(assets,cfg['root'])}

def sync():
    if MODE=='live' and not ALLOW_WRITE:
        raise IntegrationError('Live writes disabled: set ENABLE_LIVE_WRITES=true only after reviewing a dry run')
    with LOCK:
        assets,albums,client=fetch();cfg=config();all_mappings=read_json(STATE,{})
        if not cfg.get('root'):raise IntegrationError('Choose a Photos source first')
        prefix=mapping_prefix(cfg['root'])
        live_ids={str(album['id']) for album in albums}
        stale_keys=[key for key,value in all_mappings.items()
                    if key.startswith(prefix) and str(value) not in live_ids]
        if stale_keys:
            for key in stale_keys:
                del all_mappings[key]
            write_json(STATE,all_mappings)
        mapping={key[len(prefix):]:value for key,value in all_mappings.items()
                 if key.startswith(prefix)}
        rows=plan(assets,albums,cfg,mapping)
        made=0;added=0
        for row in rows:
            identifier=row['album_id']
            if not identifier:
                if client:
                    identifier=client.create_album(row['album'])
                else:
                    identifier='demo-'+secrets.token_hex(8)
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
    def _send(self,status,obj,set_cookie=None):
        data=json.dumps(obj).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        if set_cookie:self.send_header('Set-Cookie',set_cookie)
        self.end_headers();self.wfile.write(data)
    def _redirect(self,path):
        self.send_response(303);self.send_header('Location',path);self.send_header('Cache-Control','no-store');self.send_header('Content-Length','0');self.end_headers()
    def _session_token(self):
        cookies=SimpleCookie()
        try:cookies.load(self.headers.get('Cookie',''))
        except CookieError:return ''
        item=cookies.get('zima_session')
        return item.value if item else ''
    def _authorized(self):
        return valid_session(self._session_token())
    def _dispatch(self):
        if self.command=='POST':
            source=self.headers.get('Origin') or self.headers.get('Referer','')
            actual=urlsplit(source)
            if actual.netloc!=self.headers.get('Host','') or actual.scheme not in ('http','https'):
                return self._send(403,{'error':'Cross-origin request blocked'})
        try:
            if self.command=='GET':
                if self.path=='/api/health':return self._send(200,{'ok':True,'mode':MODE})
                if urlsplit(self.path).path=='/style.css':return self._static('style.css','text/css; charset=utf-8')
                if self.path=='/fonts/Montserrat-variable.ttf':return self._static('fonts/Montserrat-variable.ttf','font/ttf')
                if self.path in ('/dashboard.png', '/refresh.png', '/lan.png'):
                    return self._static(self.path[1:], 'image/png')
                if self.path=='/link.png':return self._static('link.png','image/png')
                if self.path=='/unlink.png':return self._static('unlink.png','image/png')
                if self.path=='/login.js':return self._static('login.js','application/javascript; charset=utf-8')
                if self.path in ('/','/index.html'):
                    return self._redirect('/app' if self._authorized() else '/login')
                if self.path in ('/login','/login.html'):
                    return self._redirect('/app') if self._authorized() else self._static('login.html','text/html; charset=utf-8')
                if not self._authorized():
                    return self._redirect('/login') if self.path=='/app' else self._send(401,{'error':'Please sign in'})
                if self.path=='/app':return self._static('index.html','text/html; charset=utf-8')
                if urlsplit(self.path).path=='/app.js':return self._static('app.js','application/javascript; charset=utf-8')
                if self.path=='/api/status':
                    info=connection_info()
                    return self._send(200,{'mode':MODE,'live_writes_enabled':ALLOW_WRITE,
                        'timezone':APP_TIMEZONE,
                        'connected':MODE=='demo' or info['connected'],'url':info['url'],
                        'name':info['name'],'active':info['active'],
                        'remember_connection':info['remember_connection'],
                        'configuration':config(),
                        'history':read_json(HISTORY,[])[:10]})
                if self.path=='/api/sources':return self._send(200,{'items':get_client().sources()} if MODE=='live' else {'items':[{'id':'demo','path':'/media/HDD-Storage/Gallery','available':True,'status':'demo'}]})
                if self.path=='/api/preview':return self._send(200,snapshot())
                if self.path=='/api/history':return self._send(200,read_json(HISTORY,[]))
                return self._send(404,{'error':'Not found'})
            if self.command=='POST':
                if self.path=='/api/logout':
                    revoke_session(self._session_token())
                    return self._send(200,{'ok':True},cookie_header(clear=True))
                if self.path!='/api/login' and not self._authorized():
                    return self._send(401,{'error':'Please sign in'})
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>1048576: return self._send(413,{'error':'Payload too large'})
                raw=self.rfile.read(length)
                payload=json.loads(raw or b'{}')
                if self.path=='/api/login':
                    address=self.client_address[0]
                    if not login_allowed(address):return self._send(429,{'error':'Too many attempts. Try again in a minute.'})
                    username=payload.get('username') if isinstance(payload,dict) else None
                    password=payload.get('password') if isinstance(payload,dict) else None
                    if not isinstance(username,str) or not isinstance(password,str) or not (
                        hmac.compare_digest(username,'admin') and hmac.compare_digest(password,PASSWORD)
                    ):
                        record_login_failure(address)
                        return self._send(401,{'error':'Incorrect username or password'})
                    with LOCK:LOGIN_FAILURES.pop(address,None)
                    remember=payload.get('remember',False)
                    if type(remember) is not bool:raise ValueError('Invalid remember setting')
                    token,ttl=create_session(remember)
                    return self._send(200,{'ok':True},cookie_header(token,ttl=ttl))
                if self.path=='/api/connect':return self._send(200,connect(payload))
                if self.path=='/api/connection/disconnect':return self._send(200,disconnect_connection())
                if self.path=='/api/connection/reconnect':return self._send(200,reconnect_connection())
                if self.path=='/api/connection/delete':return self._send(200,delete_connection())
                if self.path=='/api/config':return self._send(200,update_config(payload))
                if self.path=='/api/sync':
                    if payload.get('confirm')!='SYNC':raise ValueError('Explicit SYNC confirmation required')
                    result=sync()
                    log_event('Manual sync completed: created=%s added=%s' %
                              (result['created'],result['added']))
                    return self._send(200,result)
                return self._send(404,{'error':'Not found'})
            return self._send(405,{'error':'Method not allowed'})
        except (IntegrationError,ValueError,KeyError,TypeError,OverflowError) as exc:
            return self._send(400,{'error':str(exc)})
        except Exception:
            self.log_error('Unhandled error on %s',self.path)
            return self._send(500,{'error':'Unexpected server error; see container logs'})
    def _static(self,filename,mimetype):
        data=(BASE/'static'/filename).read_bytes()
        self.send_response(200);self.send_header('Content-Type',mimetype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(data)
    def do_GET(self):self._dispatch()
    def do_POST(self):self._dispatch()
    def log_message(self,format,*args):
        if self.path=='/api/health':return
        log_event('%s %s'%(self.address_string(),format%args))

class SyncSchedule:
    def __init__(self,settings,now):
        self.settings=(settings['root'],settings['interval_minutes'])
        self.deadline=self._deadline(now)

    def _deadline(self,now):
        root,interval=self.settings
        return now+interval*60 if root and interval else None

    def due(self,settings,now):
        current=(settings['root'],settings['interval_minutes'])
        if current!=self.settings:
            self.settings=current
            self.deadline=self._deadline(now)
            return False
        return self.deadline is not None and now>=self.deadline

    def complete(self,now):
        self.deadline=self._deadline(now)


def scheduler():
    schedule=SyncSchedule(config(),time.monotonic())
    if schedule.deadline is not None:
        log_event('Automatic sync scheduled: every %s minutes; first run after a full interval' %
                  schedule.settings[1])
    else:log_event('Automatic sync disabled')
    while True:
        time.sleep(30)
        settings=config()
        previous=schedule.settings
        if not schedule.due(settings,time.monotonic()):
            if schedule.settings!=previous:
                if schedule.deadline is not None:
                    log_event('Automatic sync scheduled: every %s minutes; first run after a full interval' %
                              schedule.settings[1])
                else:log_event('Automatic sync disabled')
            continue
        try:
            if MODE=='live' and not ALLOW_WRITE:
                log_event('Scheduled sync skipped: live writes are disabled')
            elif MODE=='live' and not connection_info()['connected']:
                log_event('Scheduled sync skipped: NAS is disconnected')
            else:
                log_event('Scheduled sync started')
                result=sync()
                log_event('Scheduled sync completed: created=%s added=%s' %
                          (result['created'],result['added']))
        except Exception as exc:log_event('Scheduled sync failed: '+str(exc))
        finally:schedule.complete(time.monotonic())

if __name__=='__main__':
    if MODE not in ('demo','live'):raise SystemExit('ZIMA_MODE must be demo or live')
    try:ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:raise SystemExit('APP_TIMEZONE must be an installed IANA timezone, for example Asia/Kolkata')
    if not PASSWORD or PASSWORD in ('REPLACE_WITH_STRONG_UNIQUE_PASSWORD','CHANGE_THIS_BEFORE_INSTALL'):
        raise SystemExit('Set a unique APP_PASSWORD in .env before starting')
    threading.Thread(target=scheduler,daemon=True).start()
    port=int(os.environ.get('PORT','8765'))
    log_event('Starting Zima Album Sync in '+MODE+' mode on '+str(port)+'; timezone '+APP_TIMEZONE)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
