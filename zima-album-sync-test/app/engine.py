"""Folder-to-album engine. API endpoints are UNOFFICIAL (observed in ZimaOS 1.8.0)."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

TOKEN_REFRESH_LOCK = threading.RLock()

DEMO_ASSETS = [
    {'id':'d1','path':'/media/HDD-Storage/Gallery/Watches/Seiko/s1.jpg'},
    {'id':'d2','path':'/media/HDD-Storage/Gallery/Watches/Casio/c1.heic'},
    {'id':'d3','path':'/media/HDD-Storage/Gallery/Trips/Korea/Seoul/a.jpg'},
    {'id':'d4','path':'/media/HDD-Storage/Gallery/Trips/Korea/Seoul/b.heic'},
    {'id':'d5','path':'/media/HDD-Storage/Gallery/Trips/Korea/Busan/c.jpg'},
    {'id':'d6','path':'/media/HDD-Storage/Gallery/Trips/Japan/Osaka/d.jpg'},
    {'id':'d7','path':'/media/HDD-Storage/Gallery/Family/reunion.jpg'},
]

class IntegrationError(RuntimeError):
    pass


def valid_base_url(value):
    if not isinstance(value,str):return False
    parsed=urllib.parse.urlsplit(value)
    return parsed.scheme in ('http','https') and bool(parsed.hostname) and not parsed.username \
        and not parsed.password and parsed.path in ('','/') and not parsed.query and not parsed.fragment


def validate_path(path):
    if not isinstance(path,str) or not path or '\\' in path or '\x00' in path:
        return False
    bits = path.split('/')
    return all(bit not in ('.','..') for bit in bits) and all(bit for bit in bits[1:])


def relative_folder(asset_path, root):
    if not validate_path(asset_path) or not validate_path(root) or not root.startswith('/'):
        return None
    root = root.rstrip('/')
    if asset_path.startswith('/'):
        if not asset_path.startswith(root + '/'):
            return None
        rel = asset_path[len(root)+1:]
    else:
        rel = asset_path
    if '/' not in rel:
        return ''  # media directly under source root
    return rel.rsplit('/',1)[0]


def plan(assets,albums,config,mapping):
    """Plan one album per folder with directly indexed media."""
    root=config.get('root')
    if not root:
        raise IntegrationError('Choose a Photos source before previewing albums')
    by_folder=defaultdict(set)
    for asset in assets:
        if asset.get('entry_type') == 'group' or asset.get('media_type') not in (None,'img','video'):
            continue
        folder=relative_folder(asset.get('path'),root)
        ident=asset.get('file_id') or asset.get('id')
        if folder is not None and ident is not None:
            by_folder[folder or '.'].add(str(ident))
    leaf_counts=defaultdict(int)
    for folder in by_folder:
        leaf=(root.rstrip('/').rsplit('/',1)[-1] if folder=='.' else folder.rsplit('/',1)[-1])
        leaf_counts[leaf.casefold()]+=1
    title_ids=defaultdict(list)
    ids={}
    for album in albums:
        ident=str(album['id'])
        ids[ident]=album
        title_ids[album['name']].append(ident)
    rows=[]
    for folder,asset_ids in sorted(by_folder.items()):
        leaf=(root.rstrip('/').rsplit('/',1)[-1] if folder=='.' else folder.rsplit('/',1)[-1])
        title=(root if folder=='.' else folder) if leaf_counts[leaf.casefold()]>1 else leaf
        album_id=mapping.get(folder)
        if album_id:
            album_id=str(album_id)
            if album_id not in ids:
                raise IntegrationError('Saved album for '+folder+' was deleted; review the mapping before syncing')
        else:
            matches=title_ids.get(title,[])
            if len(matches)>1:
                raise IntegrationError('More than one existing album is called '+title)
            album_id=matches[0] if matches else None
        rows.append({'folder':folder,'album':title,'album_id':album_id,
                     'count':len(asset_ids),'missing':None,
                     'status':'existing' if album_id else 'create','asset_ids':sorted(asset_ids)})
    return rows


class PhotosClient:
    def __init__(self,base_url,credentials_path,timeout=20):
        if not valid_base_url(base_url):
            raise IntegrationError('ZimaOS URL must be an http:// or https:// address without a path')
        self.url=base_url.rstrip('/')
        self.path=credentials_path
        self.timeout=timeout
        self.tokens={}
        self._load()

    def _load(self):
        try:
            with open(self.path,encoding='utf-8') as f: self.tokens=json.load(f)
        except (OSError,ValueError) as exc:
            raise IntegrationError('Cannot read credentials.json: '+str(exc)) from exc
        if not self.tokens.get('access_token'):
            raise IntegrationError('No access_token in credentials.json')

    def _save(self):
        tmp=self.path+'.tmp'
        with open(tmp,'w',encoding='utf-8') as f:
            json.dump(self.tokens,f); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,self.path)

    def request(self,method,path,body=None,auth=True,retry=True):
        if auth and self.tokens.get('refresh_token') and float(self.tokens.get('expires_at') or 0) < time.time()+900:
            self.refresh()
        headers={'Accept':'application/json'}
        if auth: headers['Authorization']=self.tokens['access_token'] # raw JWT per observed version
        if body is not None: headers['Content-Type']='application/json'
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.url+path,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as resp:
                raw=resp.read(8*1024*1024)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code==401 and auth and retry and self.tokens.get('refresh_token'):
                self.refresh()
                return self.request(method,path,body,auth,False)
            raise IntegrationError(f'Photos API {method} {path.split("?")[0]} failed HTTP {exc.code}') from exc
        except (urllib.error.URLError,ValueError) as exc:
            raise IntegrationError('Photos API request failed: '+str(exc)) from exc

    def refresh(self):
        with TOKEN_REFRESH_LOCK:
            previous_access=self.tokens.get('access_token')
            previous_refresh=self.tokens.get('refresh_token')
            self._load()
            if self.tokens.get('access_token')!=previous_access or self.tokens.get('refresh_token')!=previous_refresh:
                return  # Another request already saved rotated credentials.
            refresh_token=self.tokens.get('refresh_token')
            if not refresh_token:
                raise IntegrationError('Access expired, and no refresh token configured')
            # Actual response envelope may differ by installed ZimaOS build; fail closed.
            headers={'Content-Type':'application/json','Accept':'application/json',
                     'Authorization':self.tokens['access_token']}
            req=urllib.request.Request(self.url+'/v1/users/refresh',data=json.dumps({'refresh_token':refresh_token}).encode(),headers=headers,method='POST')
            try:
                with urllib.request.urlopen(req,timeout=self.timeout) as r: out=json.load(r)
            except (urllib.error.HTTPError,urllib.error.URLError,ValueError) as exc:
                raise IntegrationError('Photos authentication refresh failed; reconnect credentials') from exc
            if isinstance(out,dict) and out.get('success') != 200:
                raise IntegrationError('Photos authentication refresh was rejected')
            if isinstance(out,dict) and isinstance(out.get('data'),dict): out=out['data']
            if not isinstance(out,dict) or not all(k in out for k in ('access_token','refresh_token','expires_at')):
                raise IntegrationError('Unrecognized refresh response; tokens left unchanged')
            self.tokens.update({k:out[k] for k in ('access_token','refresh_token','expires_at')})
            self._save()

    @staticmethod
    def entries(payload,keys):
        if isinstance(payload,list): return payload
        if not isinstance(payload,dict): raise IntegrationError('Unexpected Photos API response shape')
        for k in keys:
            if isinstance(payload.get(k),list): return payload[k]
        nested=payload.get('data')
        if isinstance(nested,list): return nested
        if isinstance(nested,dict): return PhotosClient.entries(nested,keys)
        raise IntegrationError('Could not identify list in Photos API response; stopping safely')

    def gallery(self):
        results=[]; cursor=None; seen=set()
        for _ in range(1000):
            params={'media_types':'img,video','limit':200,'collapse_groups':'false'}
            if cursor: params['cursor']=cursor
            result=self.request('GET','/v2/photos/gallery/assets?'+urllib.parse.urlencode(params))
            results.extend(self.entries(result,('assets','entries','items')))
            envelope=result.get('data',result) if isinstance(result,dict) else {}
            nxt=envelope.get('next_cursor') if isinstance(envelope,dict) else None
            if not nxt:
                total=envelope.get('total') if isinstance(envelope,dict) else None
                if isinstance(total,int) and len(results)<total:
                    raise IntegrationError('Gallery pagination incomplete; refusing partial results')
                return [x for x in results if isinstance(x,dict) and x.get('entry_type')!='group']
            if nxt in seen or not self.entries(result,('assets','entries','items')): raise IntegrationError('Repeated or empty gallery page; refusing partial results')
            seen.add(nxt);cursor=nxt
        raise IntegrationError('Gallery pagination limit exceeded')

    def albums(self):
        out=self.request('GET','/v2/photos/albums')
        records=self.entries(out,('albums','items'))
        envelope=out.get('data',out) if isinstance(out,dict) else {}
        if isinstance(envelope,dict) and (envelope.get('next_cursor') or (isinstance(envelope.get('total'),int) and len(records)<envelope['total'])):
            raise IntegrationError('Album list pagination detected; refusing incomplete list')
        result=[]
        for a in records:
            if isinstance(a,dict) and (a.get('album_id') is not None or a.get('id') is not None) and isinstance(a.get('name'),str):
                result.append({'id':str(a.get('album_id') if a.get('album_id') is not None else a['id']),'name':a['name']})
        if len(result)!=len(records): raise IntegrationError('Unrecognized album fields')
        return result

    def members(self,ident):
        ids=set();cursor=None;seen=set()
        for _ in range(1000):
            q={'limit':200}
            if cursor: q['cursor']=cursor
            out=self.request('GET','/v2/photos/albums/'+urllib.parse.quote(str(ident),safe='')+'?'+urllib.parse.urlencode(q))
            entries=self.entries(out,('assets','items','entries'))
            for a in entries:
                val=a.get('file_id') or a.get('id') if isinstance(a,dict) else None
                if val is not None: ids.add(str(val))
            envelope=out.get('data',out) if isinstance(out,dict) else {}
            nxt=envelope.get('next_cursor') if isinstance(envelope,dict) else None
            if not nxt:
                total=envelope.get('total') if isinstance(envelope,dict) else None
                if isinstance(total,int) and len(ids)<total:
                    raise IntegrationError('Album members incomplete')
                return ids
            if nxt in seen: raise IntegrationError('Repeated album cursor')
            seen.add(nxt);cursor=nxt
        raise IntegrationError('Album pagination limit exceeded')

    def create_album(self,name):
        out=self.request('POST','/v2/photos/albums',{'name':name})
        result=out.get('data',out) if isinstance(out,dict) else {}
        if isinstance(result,dict) and isinstance(result.get('album'),dict): result=result['album']
        ident=result.get('album_id',result.get('id')) if isinstance(result,dict) else None
        if ident is None:
            raise IntegrationError('Album creation returned no ID; inspect Photos before retry')
        return str(ident)

    def sources(self):
        out=self.request('GET','/v2/photos/sources')
        records=self.entries(out,('items','sources'))
        result=[]
        for source in records:
            if not isinstance(source,dict) or not isinstance(source.get('path'),str) or source.get('id') is None:
                raise IntegrationError('Unrecognized Photos source fields')
            result.append({'id':str(source['id']),'path':source['path'],
                           'available':source.get('available',True),'status':source.get('status','')})
        return result

    @staticmethod
    def login(base_url,username,password,timeout=20):
        if not valid_base_url(base_url):
            raise IntegrationError('ZimaOS URL must be an http:// or https:// address without a path')
        if not username or not password:
            raise IntegrationError('ZimaOS username and password are required')
        req=urllib.request.Request(base_url.rstrip('/')+'/v1/users/login',
            data=json.dumps({'username':username,'password':password}).encode(),
            headers={'Content-Type':'application/json','Accept':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=timeout) as resp: out=json.load(resp)
        except (urllib.error.HTTPError,urllib.error.URLError,ValueError) as exc:
            raise IntegrationError('ZimaOS login failed') from exc
        if not isinstance(out,dict) or out.get('success')!=200 or not isinstance(out.get('data'),dict):
            raise IntegrationError('ZimaOS login returned an unexpected response')
        token=out['data'].get('token')
        if not isinstance(token,dict) or not all(token.get(k) for k in ('access_token','refresh_token','expires_at')):
            raise IntegrationError('ZimaOS login returned incomplete credentials')
        return {k:token[k] for k in ('access_token','refresh_token','expires_at')}

    def add_members(self,ident,ids):
        for start in range(0,len(ids),30):
            self.request('POST','/v2/photos/albums/'+urllib.parse.quote(str(ident),safe='')+'/assets',{'asset_ids':ids[start:start+30]})
