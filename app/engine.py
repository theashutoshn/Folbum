"""Folder-to-album engine. API endpoints are UNOFFICIAL (observed in ZimaOS 1.8.0)."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import PurePosixPath

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


def validate_path(path):
    if not isinstance(path,str) or not path or '\\' in path or '\x00' in path:
        return False
    bits = path.split('/')
    return all(bit not in ('.','..') for bit in bits)


def relative_folder(asset_path, root):
    if not validate_path(asset_path) or not validate_path(root) or not root.startswith('/'):
        return None
    root = root.rstrip('/')
    if not asset_path.startswith(root + '/'):
        return None
    rel = asset_path[len(root)+1:]
    if '/' not in rel:
        return ''  # media directly under source root
    return rel.rsplit('/',1)[0]


def folder_tree(assets, root):
    folders = set()
    counts = defaultdict(int)
    for a in assets:
        rel = relative_folder(a.get('path',''),root)
        if rel is None:
            continue
        counts[rel] += 1
        bits = rel.split('/') if rel else []
        for i in range(1,len(bits)+1):
            folders.add('/'.join(bits[:i]))
    return [{'path':p,'depth':p.count('/'),'count':counts[p]} for p in sorted(folders, key=lambda p:(p.lower(),p))]


def target_assets(assets,root,folder,recursive):
    result = set()
    for a in assets:
        rel = relative_folder(a.get('path',''),root)
        if rel is None:
            continue
        if rel == folder or (recursive and rel.startswith(folder+'/')):
            ident = a.get('file_id') or a.get('id')
            if ident is not None:
                result.add(str(ident))
    return result


def album_name(folder,mode):
    return folder.rsplit('/',1)[-1] if mode == 'leaf' else folder.replace('/',' / ')


def plan(assets,albums,config,mapping):
    """Calculate operations without mutations. Reject ambiguous names and stale IDs."""
    available = {f['path'] for f in folder_tree(assets,config['root'])}
    rules = config.get('rules',{})
    chosen = {p:r for p,r in rules.items() if r.get('enabled')}
    title_ids = defaultdict(list)
    ids = {}
    for album in albums:
        ident = str(album['id'])
        ids[ident] = album
        title_ids[album['name']].append(ident)
    rows=[]
    used_names={}
    for folder,rule in sorted(chosen.items()):
        if folder not in available:
            # Folder might be physically present but not yet indexed.
            rows.append({'folder':folder,'status':'not-indexed','count':0,'missing':0,'album':rule.get('name') or album_name(folder,config.get('naming','path'))})
            continue
        name=(rule.get('name') or album_name(folder,config.get('naming','path'))).strip()
        if not name:
            raise IntegrationError('Album title cannot be empty: '+folder)
        if name in used_names and used_names[name] != folder:
            raise IntegrationError('Two rules produce the same album name: '+name)
        used_names[name]=folder
        album_id = mapping.get(folder)
        if album_id and str(album_id) not in ids:
            raise IntegrationError('Stale saved album mapping for '+folder+'; review state before applying')
        if not album_id:
            matches=title_ids.get(name,[])
            if len(matches)>1:
                raise IntegrationError('Ambiguous existing albums called '+name)
            # Only adopt when explicitly opted in; otherwise create separate plugin-managed album
            album_id = matches[0] if (matches and config.get('adopt_existing',False)) else None
        target=target_assets(assets,config['root'],folder,bool(rule.get('recursive',False)))
        rows.append({'folder':folder,'album':name,'album_id':str(album_id) if album_id else None,'count':len(target),'missing':None,'status':'existing' if album_id else 'create','asset_ids':sorted(target)})
    return rows


class PhotosClient:
    def __init__(self,base_url,credentials_path,timeout=20):
        if not base_url.startswith(('http://','https://')):
            raise IntegrationError('ZIMA_URL must start with http:// or https://')
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
        refresh_token=self.tokens.get('refresh_token')
        if not refresh_token:
            raise IntegrationError('Access expired, and no refresh token configured')
        # Actual response envelope may differ by installed ZimaOS build; fail closed.
        headers={'Content-Type':'application/json','Accept':'application/json'}
        req=urllib.request.Request(self.url+'/v1/users/refresh',data=json.dumps({'refresh_token':refresh_token}).encode(),headers=headers,method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r: out=json.load(r)
        except (urllib.error.HTTPError,urllib.error.URLError,ValueError) as exc:
            raise IntegrationError('Photos authentication refresh failed; reconnect credentials') from exc
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
            if nxt in seen: raise IntegrationError('Repeated gallery cursor; refusing partial results')
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
            if isinstance(a,dict) and a.get('id') is not None and isinstance(a.get('name'),str):
                result.append({'id':str(a['id']),'name':a['name']})
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
        if not isinstance(result,dict) or result.get('id') is None:
            raise IntegrationError('Album creation returned no ID; inspect Photos before retry')
        return str(result['id'])

    def add_members(self,ident,ids):
        for start in range(0,len(ids),30):
            self.request('POST','/v2/photos/albums/'+urllib.parse.quote(str(ident),safe='')+'/assets',{'asset_ids':ids[start:start+30]})
