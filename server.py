#!/usr/bin/env python3
"""Avelora Online Combat Manager — one-service hosted server.

DM password authentication, server-authoritative gameplay, HTTPS-ready session
cookies and persistent volume-backed SQLite database.
"""
import argparse
import hmac
import hashlib
import signal
from collections import defaultdict, deque
import copy
import datetime
import ipaddress
import json
import os
import random
import re
import secrets
import socket
import sqlite3
import threading
import time
import traceback
import urllib.parse
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from rules import BASE_POKE, clamp, computed, attack_dice, hit_bonus, defense_ac, damage, pokemon_view, choose_moves, fallback_mon, health_band

ROOT=Path(__file__).resolve().parent
ONLINE=os.environ.get('AVELORA_ONLINE','0')=='1'
DM_PASSWORD=os.environ.get('AVELORA_DM_PASSWORD','')
if ONLINE and len(DM_PASSWORD)<16:
    raise RuntimeError('Missing or too-short AVELORA_DM_PASSWORD. In Railway > Avelora service > Variables, set AVELORA_DM_PASSWORD to a NEW private password of at least 16 characters, then deploy the changes. Do not put the password in GitHub.')
DATA=Path(os.environ.get('AVELORA_DATA_DIR',str(ROOT/'data'))); DATA.mkdir(parents=True, exist_ok=True)
LOGIN_LOCK=threading.RLock()
FAILS=defaultdict(deque)
COOKIE_NAME='__Host-avelora_session' if ONLINE else 'avelora_session'
COOKIE_FLAGS='; HttpOnly; SameSite=Strict; Secure; Path=/' if ONLINE else '; HttpOnly; SameSite=Strict; Path=/'

def throttle(ip):
    with LOGIN_LOCK:
        bucket=FAILS[ip];t=time.monotonic()
        while bucket and t-bucket[0]>900:bucket.popleft()
        if len(bucket)>=12:raise PermissionError('Too many sign-in attempts. Wait 15 minutes and try again.')

def failed(ip):
    with LOGIN_LOCK:
        FAILS[ip].append(time.monotonic())

def authenticated_dm(password):
    if not ONLINE:return False
    # Hash first to avoid string-length timing artifacts; credentials are never logged.
    return hmac.compare_digest(hashlib.sha256(str(password).encode('utf-8')).digest(), hashlib.sha256(DM_PASSWORD.encode('utf-8')).digest())
DB=DATA/'avelora.sqlite3'
ALLOWED_STATUS={'none','burn','poison','bad-poison','sleep','freeze','paralysis','confusion'}
TYPES={'normal','fire','water','electric','grass','ice','fighting','poison','ground','flying','psychic','bug','rock','ghost','dragon','dark','steel','fairy'}
STAGES={'attack','defense','special-attack','special-defense','speed','accuracy','evasion'}
WEATHERS={'none','sun','rain','sand','snow'}
TERRAINS={'none','electric','grassy','misty','psychic'}
AREAS={'earthquake':'all-other-pokemon','surf':'all-other-pokemon','discharge':'all-other-pokemon','bulldoze':'all-other-pokemon','explosion':'all-other-pokemon','rock-slide':'all-opponents','razor-leaf':'all-opponents','heat-wave':'all-opponents','swift':'all-opponents'}
DEFAULT_GAME={'room_code':''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6)),'title':'Echoes of Avelora','players':{},'pokemon':{},'battle':None,'requests':[], 'change_history':[], 'version':0, 'created':datetime.datetime.now(datetime.timezone.utc).isoformat()}

def eid():return uuid.uuid4().hex[:14]
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def display(n):return str(n or '').replace('-',' ').title()
def clean(s,n=40):return re.sub(r'[<>\x00-\x1f]','',str(s or '')).strip()[:n]
def toint(v,lo,hi):
    try:
        n=int(v)
        if isinstance(v,bool) or n!=float(v):raise ValueError()
    except (ValueError,TypeError,OverflowError):raise ValueError(f'Expected a whole number from {lo} to {hi}')
    if not lo<=n<=hi:raise ValueError(f'Expected a whole number from {lo} to {hi}')
    return n

def new_state():return copy.deepcopy(DEFAULT_GAME)

class App:
    def __init__(self):
        self.lock=threading.RLock(); self.condition=threading.Condition(self.lock)
        self.db=sqlite3.connect(DB,check_same_thread=False,timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=20000')
        self.db.execute('CREATE TABLE IF NOT EXISTS saved (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, role TEXT NOT NULL, player_id TEXT, made TEXT NOT NULL)')
        self.db.commit()
        row=self.db.execute('SELECT data FROM saved WHERE id=1').fetchone()
        if row:self.state=json.loads(row[0])
        else:self.state=new_state();self.persist()
        self.mutations=0; self.last_backup=0
    def persist(self):
        self.db.execute('INSERT INTO saved(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(json.dumps(self.state,ensure_ascii=False),));self.db.commit()
    def changed(self):
        self.state['version']=self.state.get('version',0)+1
        self.persist();self.mutations+=1;self.condition.notify_all()
        if self.mutations%25==0:self.backup()
    def backup(self):
        # SQLite online backup API ensures consistent snapshots even under WAL.
        dest=DATA/'backups';dest.mkdir(exist_ok=True)
        fname=dest/('avelora_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+str(self.state['version'])+'.sqlite3')
        conn=sqlite3.connect(fname)
        try:self.db.backup(conn)
        finally:conn.close()
        files=sorted(dest.glob('avelora_*.sqlite3'))
        for p in files[:-10]:p.unlink(missing_ok=True)
        self.last_backup=time.time()
        return str(fname.name)
    def create_session(self,role,player_id=None):
        import hashlib
        token=secrets.token_urlsafe(32); hashed=hashlib.sha256(token.encode()).hexdigest()
        stamp=('dm:'+hashlib.sha256(DM_PASSWORD.encode()).hexdigest()) if role=='dm' and ONLINE else now()
        self.db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashed,role,player_id,stamp));self.db.commit()
        return token
    def user(self, token):
        if not token:return None
        import hashlib
        row=self.db.execute('SELECT role,player_id,made FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:return None
        role,pid,stamp=row
        if role=='dm' and ONLINE and stamp!='dm:'+hashlib.sha256(DM_PASSWORD.encode()).hexdigest():return None
        if role=='player' and pid not in self.state['players']:return None
        return {'role':role,'id':pid}
    def revoke_player(self,pid):
        self.db.execute('DELETE FROM sessions WHERE player_id=?',(pid,));self.db.commit()

app=App()

def require_dm(who):
    if not who or who['role']!='dm':raise PermissionError('DM access required')

def require_player(who):
    if not who or who['role']!='player':raise PermissionError('Player access required')
    p=app.state['players'].get(who['id'])
    if not p or p['state']!='approved':raise PermissionError('DM must approve your Trainer first')
    return p

def sanitize_battle(b,who):
    if not b:return None
    if who['role']=='dm':return {k:copy.deepcopy(v) for k,v in b.items() if k!='_history'}
    pid=who['id']; out={k:copy.deepcopy(v) for k,v in b.items() if k not in ('units','_history')}
    # All enemy and other Trainer information stays deliberately limited.
    out['units']=[]
    for u in b['units']:
        if u.get('trainer_id')==pid:
            x=copy.deepcopy(u);x['calculated']=computed(u)
        else:
            x={'id':u['id'],'pokemon_id':u['pokemon_id'],'team':u['team'],'trainer_id':u['trainer_id'],
               'name':u.get('nickname') or u['species'],'species':u['species'],'dex_id':u.get('dex_id'),
               'status':u.get('status','none'),'health':health_band(u['current_hp'],computed(u)['max_hp']),
               'active':u['active'],'acted':u['acted'],'initiative':u['initiative'],
               'types':u.get('types',[]),'shiny':u.get('shiny',False),'mega_active':u.get('mega_active',False),
               'tera_active':u.get('tera_active',False),'tera_type':u.get('tera_type') if u.get('tera_active') else None,
               'revealed_moves':u.get('revealed_moves',[])}
        out['units'].append(x)
    return out

def projection(who):
    s=app.state
    if not who:return {'signed_in':False,'version':s['version'],'room_ready':True,'host_login':False, 'online':ONLINE}
    if who['role']=='dm':
        return {'signed_in':True,'role':'dm','online':ONLINE,'room_code':s['room_code'],'title':s['title'],'players':list(s['players'].values()),
                'pokemon':[pokemon_view(p) for p in s['pokemon'].values()], 'requests':s['requests'], 'change_history':s.get('change_history',[]), 'battle':sanitize_battle(s['battle'],who), 'version':s['version']}
    player=s['players'][who['id']]
    if player['state']!='approved':return {'signed_in':True,'role':'player','player':player,'pending':True,'online':ONLINE,'version':s['version']}
    return {'signed_in':True,'role':'player','player':player,'online':ONLINE,'title':s['title'],'room_code':s['room_code'],
            'pokemon':[pokemon_view(p) for p in s['pokemon'].values() if p.get('owner')==who['id']],
            'requests':[r for r in s['requests'] if r['player_id']==who['id']],
            'change_history':[r for r in s.get('change_history',[]) if r['player_id']==who['id']][-25:],
            'battle':sanitize_battle(s['battle'],who),'version':s['version']}

def mon_card_from_input(d):
    """Only the DM can supply base PokéAPI data; player controls never accept this."""
    name=clean(d.get('species','').lower().replace(' ','-'),65)
    if not re.fullmatch(r'[a-z0-9-]{2,65}',name):raise ValueError('Choose a valid Pokémon species')
    lvl=toint(d.get('level',5),1,100)
    stats=d.get('stats')
    if not isinstance(stats,list) or len(stats)!=6:raise ValueError('Pokémon requires all six official base stats')
    stats=[toint(v,1,255) for v in stats]
    types=d.get('types')
    if not isinstance(types,list) or len(types) not in (1,2) or any(t not in TYPES for t in types):raise ValueError('Choose one or two known Pokémon types')
    ability=clean(d.get('ability',''),50).lower()
    allowed=d.get('allowed_moves',[])
    if not isinstance(allowed,list) or len(allowed)>120:raise ValueError('Too many moves')
    legal=[];seen=set()
    for m in allowed:
        if not isinstance(m,dict):continue
        mn=clean(m.get('name',''),65).lower()
        if not re.fullmatch('[a-z0-9-]{2,65}',mn) or mn in seen:continue
        if m.get('category') not in ('physical','special','status') or m.get('type') not in TYPES:continue
        power=None if m.get('power') is None else toint(m['power'],1,250)
        acc=None if m.get('accuracy') is None else toint(m['accuracy'],1,100)
        pp=toint(m.get('pp',15),1,64)
        learned=toint(m.get('learned_at',1),0,100)
        legal.append({'name':mn,'type':m['type'],'category':m['category'],'power':power,'accuracy':acc,'pp':pp,'learned_at':learned,
                       'effect':clean(m.get('effect',''),220), 'target':clean(m.get('target','selected-pokemon'),60),
                       'ailment':clean(m.get('ailment','none'),35), 'ailment_chance':clamp(int(m.get('ailment_chance') or 0),0,100),
                       'stat_changes':m.get('stat_changes',[])[:5] if isinstance(m.get('stat_changes'),list) else []})
        seen.add(mn)
    eligible=[m for m in legal if m['learned_at']<=lvl]
    if not eligible:raise ValueError('No level-legal moves available; try the online Pokédex or a built-in starter')
    shiny=bool(d.get('force_shiny',False)) or (secrets.randbelow(4096)==0)
    pid=d.get('owner'); pid=pid if pid in app.state['players'] and app.state['players'][pid]['state']=='approved' else None
    mon={'id':eid(),'species':name,'dex_id':toint(d.get('dex_id',0),0,20000), 'nickname':clean(d.get('nickname') or display(name),35),
         'stats':stats,'level':lvl,'types':types,'base_types':types[:], 'legendary':bool(d.get('legendary')),
         'legend_ac':bool(d.get('legend_ac') and d.get('legendary')),'shiny':shiny,'owner':pid,'slot': 'storage',
         'ability':ability, 'abilities':list({clean(a,50) for a in d.get('abilities',[ability]) if isinstance(a,str)})[:8],
         'bond_points':toint(d.get('bond_points',0),0,20),'experience':0, 'moves':choose_moves(eligible), 'allowed_moves':legal,
         'mega_enabled':bool(d.get('mega_enabled',False)), 'mega_forms':d.get('mega_forms',[])[:5] if isinstance(d.get('mega_forms'),list) else [],
         'tera_enabled':bool(d.get('tera_enabled',False)), 'tera_type':d.get('tera_type') if d.get('tera_type') in TYPES else types[0],
         'status':'none','current_hp':0, 'from_offline':bool(d.get('offline',False))}
    if mon['mega_enabled'] and not mon['mega_forms']:mon['mega_enabled']=False
    mon['current_hp']=computed(mon)['max_hp']
    inparty=sum(1 for p in app.state['pokemon'].values() if p.get('owner')==pid and p.get('slot')=='party')
    if pid and inparty<6:mon['slot']='party'
    return mon

def has_active_battle():return bool(app.state['battle'] and app.state['battle']['phase']!='finished')

def unit_by_id(b,uid):
    for u in b['units']:
        if u['id']==uid:return u
    raise ValueError('Combatant not found')

def active_actor(b):
    if b['phase']!='battle':raise ValueError('Battle has not started yet')
    if b['turn_index']<0 or b['turn_index']>=len(b['order']):raise ValueError('No active turn')
    return unit_by_id(b,b['order'][b['turn_index']])

def append_log(b,message):
    b['log'].append({'when':now(),'round':b['round'],'message':message})
    b['log']=b['log'][-150:]

def checkpoint():
    b=app.state['battle']
    if not b:return
    h=b.setdefault('_history',[])
    bare=copy.deepcopy({k:v for k,v in b.items() if k!='_history'})
    h.append({'battle':bare,'pokemon':copy.deepcopy(app.state['pokemon'])})
    if len(h)>20:del h[0]

def find_targets(b,a,m,submitted):
    name=m['name']; target_kind=AREAS.get(name,m.get('target','selected-pokemon'))
    living=[u for u in b['units'] if u['active'] and u['current_hp']>0]
    if target_kind in ('all-other-pokemon','entire-field'):return [u for u in living if u['id']!=a['id']]
    if target_kind in ('all-opponents','all-opposing-pokemon'):return [u for u in living if u['team']!=a['team']]
    if target_kind in ('user','users-field','user-or-ally','user-and-allies') and m['category']=='status':return [a]
    if len(submitted)!=1:raise ValueError('Select exactly one target')
    target=unit_by_id(b,submitted[0])
    if target not in living:raise ValueError('Target is not on the battlefield')
    if target['team']==a['team'] and m['category']!='status':raise ValueError('Choose an opponent')
    return [target]

def update_mon_hp(unit):
    p=app.state['pokemon'].get(unit['pokemon_id'])
    if p:
        p['current_hp']=unit['current_hp'];p['status']=unit.get('status','none')
        # Sync spent PP back to saved party for continuity between encounters.
        for i,m in enumerate(p.get('moves',[])):
            if i<len(unit.get('moves',[])) and m['name']==unit['moves'][i]['name']:
                m['remaining_pp']=unit['moves'][i]['remaining_pp']

def award_exp(p, gain):
    """Exact v1.3 EXP threshold and HP-on-level-up behavior."""
    p['experience']=p.get('experience',0)+gain
    levels=0
    while p['level']<100:
        need=25+p['level']*12+(p['level']//10)*20
        if p['experience']<need:break
        p['experience']-=need
        old_max=computed(p)['max_hp'];p['level']+=1
        p['current_hp']=clamp(p['current_hp']+computed(p)['max_hp']-old_max,0,computed(p)['max_hp'])
        p['evolution_alert']=True
        p['move_learning_alert']=any(m.get('learned_at')==p['level'] and m['name'] not in {x['name'] for x in p['moves']} for m in p.get('allowed_moves',[]))
        levels+=1
    if p['level']==100:p['experience']=0
    return levels

def log_status_effect(b,a,t,m):
    n=m['name']; applied=False
    changers={'growl':('attack',-1),'leer':('defense',-1),'tail-whip':('defense',-1),'swords-dance':('attack',2),'iron-defense':('defense',2),
              'nasty-plot':('special-attack',2),'calm-mind':('special-attack',1),'agility':('speed',2),'defense-curl':('defense',1),
              'amnesia':('special-defense',2),'sand-attack':('accuracy',-1)}
    if n in changers:
        key,delta=changers[n];t['stages'][key]=clamp(t['stages'][key]+delta,-6,6);applied=True
        append_log(b,f'{display(t["species"])}: {display(key)} stage {t["stages"][key]:+d}.')
    if n=='growth':
        for stat in ('attack','special-attack'):t['stages'][stat]=clamp(t['stages'][stat]+1,-6,6)
        applied=True;append_log(b,f'{display(t["species"])} grew stronger.')
    status={'thunder-wave':'paralysis','sleep-powder':'sleep','hypnosis':'sleep','will-o-wisp':'burn','toxic':'bad-poison','poison-powder':'poison'}.get(n)
    if status and t['status']=='none':
        status_immune=(status=='burn' and 'fire' in t['types']) or (status in ('poison','bad-poison') and bool(set(t['types'])&{'poison','steel'})) or (status=='paralysis' and 'electric' in t['types']) or (status=='sleep' and b.get('terrain')=='misty')
        if not status_immune:t['status']=status;t['status_turns']=random.randint(1,3) if status=='sleep' else 0;applied=True;append_log(b,f'{display(t["species"])} is affected by {status}.')
    if n in ('recover','soft-boiled','milk-drink','roost'):
        heal=max(1,computed(t)['max_hp']//2);t['current_hp']=min(computed(t)['max_hp'],t['current_hp']+heal);applied=True;append_log(b,f'{display(t["species"])} restored HP.')
    if n in ('protect','detect'):t['protected']=True;applied=True;append_log(b,f'{display(t["species"])} is protected this round.')
    if n in ('iron-defense',): t['temp_ac']['physical']=clamp(t['temp_ac']['physical']+1,-15,15)
    if not applied:append_log(b,f'{display(a["species"])} used {display(n)}. DM must adjudicate its unusual effect.')
    update_mon_hp(t)

def end_round(b):
    b['round']+=1
    for u in b['units']:
        u['acted']=False;u['protected']=False
        if u['current_hp']<=0 or not u['active']:continue
        hpmax=computed(u)['max_hp'];loss=0
        if u['status']=='burn':loss=max(1,hpmax//16)
        if u['status']=='poison':loss=max(1,hpmax//8)
        if u['status']=='bad-poison':u['toxic_turns']=u.get('toxic_turns',0)+1;loss=max(1,hpmax*u['toxic_turns']//16)
        weather=b.get('weather','none')
        if weather in ('sand','snow') and u.get('ability') not in ('magic-guard','overcoat'):
            immunities=('rock','ground','steel') if weather=='sand' else ('ice',)
            if not set(u.get('types',[]))&set(immunities):loss+=max(1,hpmax//16)
        if loss:
            u['current_hp']=max(0,u['current_hp']-loss);append_log(b,f'{display(u["species"])} took end-of-round damage.')
        if b.get('terrain')=='grassy' and u['current_hp']>0:u['current_hp']=min(hpmax,u['current_hp']+max(1,hpmax//16))
        for k in list(u['timed_mods']):
            u['timed_mods'][k]-=1
            if u['timed_mods'][k]<=0:
                if k in STAGES:u['stages'][k]=0
                if k in ('physical','special'):u['temp_ac'][k]=0
                del u['timed_mods'][k]
        update_mon_hp(u)
    append_log(b,f'Round {b["round"]} begins.')

def advance(b):
    def eligible(x):return x['active'] and x['current_hp']>0 and not x['acted']
    for i,uid in enumerate(b['order']):
        if eligible(unit_by_id(b,uid)):
            b['turn_index']=i;return
    end_round(b)
    for i,uid in enumerate(b['order']):
        if eligible(unit_by_id(b,uid)):
            b['turn_index']=i;return
    b['phase']='finished';append_log(b,'Battle finished: no Pokémon can act.')

def act_attack(who,b,d):
    a=active_actor(b)
    if who['role']!='dm' and a.get('trainer_id')!=who['id']:raise PermissionError('It is not your Pokémon’s turn')
    if not a['active'] or a['current_hp']<=0:raise ValueError('Cannot act with a benched or fainted Pokémon')
    mi=toint(d.get('move_index',-1),0,len(a['moves'])-1);m=a['moves'][mi]
    if m['remaining_pp']<=0:raise ValueError('That move has no PP')
    submitted=d.get('targets',[])
    if not isinstance(submitted,list) or len(submitted)>40:raise ValueError('Invalid target selection')
    targs=find_targets(b,a,m,[t.get('target_id') for t in submitted])
    tdata={v.get('target_id'):v for v in submitted if isinstance(v,dict)}
    if len(tdata)!=len(targs) or set(tdata)!={t['id'] for t in targs}:raise ValueError('Provide rolls for every required target, including allies hit by area moves')
    dice=attack_dice(m,a['level']); auto=m.get('accuracy') is None
    outcomes=[]
    wants_reroll=False
    for target in targs:
        td=tdata[target['id']]
        roll=None if auto else toint(td.get('d20'),1,20)
        if td.get('reroll_d20') not in (None,''):
            if auto or wants_reroll or a.get('bond_reroll_used') or computed(a)['charisma']<26:
                raise ValueError('Bond reroll is unavailable or already used')
            roll=toint(td['reroll_d20'],1,20);wants_reroll=True
        if dice is None and auto:hit=True
        else:hit=auto or roll==20 or (roll!=1 and roll+hit_bonus(a,m)>=defense_ac(target,m.get('category')))
        if m['name'] in ('swift','aura-sphere','magical-leaf','disarming-voice'):hit=True
        count=dice['count']*(2 if roll==20 else 1) if dice else 0
        dmg_total=toint(td.get('dice_sum',0),count,count*dice['sides']) if dice and hit else 0
        outcomes.append((target,roll,hit,dmg_total))
    checkpoint()
    if wants_reroll:
        a['bond_reroll_used']=True
        append_log(b,f'{display(a["species"])} used its high-Bond d20 reroll!')
    # Physical-dice rolls are submitted by players; status checks remain server-authoritative.
    prevented=False
    if a['status']=='sleep' and a.get('status_turns',0)>0:
        a['status_turns']-=1;prevented=a['status_turns']>0
        if not prevented:a['status']='none';append_log(b,f'{display(a["species"])} woke up.')
    elif a['status']=='freeze':
        prevented=random.random()>=.20
        if not prevented:a['status']='none'
    elif a['status']=='paralysis':prevented=random.random()<.25
    if a.get('status')=='confusion' and not a.get('confused_turns',0):a['confused_turns']=random.randint(2,4)
    if a.get('confused_turns',0)>0:
        a['confused_turns']-=1
        if random.random()<.33:
            a['current_hp']=max(0,a['current_hp']-max(1,computed(a)['max_hp']//12));prevented=True;append_log(b,f'{display(a["species"])} hurt itself in confusion.')
    m['remaining_pp']-=1
    if prevented:append_log(b,f'{display(a["species"])} could not act because of its condition.')
    else:
        a['participated']=True;a['revealed_moves']=list(set(a.get('revealed_moves',[])+[m['name']]))
        for t,roll,hit,dice_sum in outcomes:
            if not hit:append_log(b,f'{display(a["species"])} used {display(m["name"])} but missed {display(t["species"])}.');continue
            if dice:
                amount,eff=damage(a,t,m,dice_sum,crit=roll==20,weather=b.get('weather','none'),terrain=b.get('terrain','none'))
                t['current_hp']=max(0,t['current_hp']-amount)
                append_log(b,f'{display(a["species"])} used {display(m["name"])} on {display(t["species"])}: {amount} damage'+(' (super effective)' if eff>1 else ' (resisted)' if 0<eff<1 else ' (immune)' if eff==0 else '')+(' (critical)' if roll==20 else '')+'.')
                if amount>0 and t['current_hp']>0 and m.get('ailment') in ALLOWED_STATUS-{'none'} and random.randrange(100)<int(m.get('ailment_chance',0)) and t['status']=='none':
                    t['status']=m['ailment'];t['status_turns']=random.randint(1,3) if t['status']=='sleep' else 0;append_log(b,f'{display(t["species"])} is now {t["status"]}.')
                if t['current_hp']==0:
                    append_log(b,f'{display(t["species"])} fainted!')
                    # Fainting awards XP to participating Pokémon on the opposing team.
                    gain=20+8*t['level']+int(t['stats'][0]/5+0.5)
                    candidates=[u for u in b['units'] if u['team']!=t['team'] and u.get('participated') and u['pokemon_id'] in app.state['pokemon']]
                    if candidates:
                        share=max(1,gain//len(candidates))
                        for ally in candidates:
                            p=app.state['pokemon'][ally['pokemon_id']];oldmax=computed(ally)['max_hp'];ups=award_exp(p,share);ally['level']=p['level'];ally['current_hp']=clamp(ally['current_hp']+computed(ally)['max_hp']-oldmax,0,computed(ally)['max_hp']);append_log(b,f'{display(ally["species"])} reached Level {p["level"]}!' ) if ups else None
                        append_log(b,f'Participating Pokémon gained {share} EXP each.')
                update_mon_hp(t)
            else:log_status_effect(b,a,t,m)
    update_mon_hp(a);a['acted']=True;advance(b)

def new_battle(d):
    allies=d.get('allies',[]);enemies=d.get('enemies',[])
    if not isinstance(allies,list) or not isinstance(enemies,list):raise ValueError('Choose both teams')
    if not 1<=len(allies)<=20 or not 1<=len(enemies)<=20:raise ValueError('Each side must have between 1 and 20 Pokémon')
    if len(allies)!=len(set(allies)) or len(enemies)!=len(set(enemies)) or set(allies)&set(enemies):raise ValueError('A Pokémon cannot enter twice')
    for pkid in allies+enemies:
        if pkid not in app.state['pokemon']:raise ValueError('Battle Pokémon not found')
    slots={'ally':toint(d.get('ally_slots',len(allies)),1,len(allies)), 'enemy':toint(d.get('enemy_slots',len(enemies)),1,len(enemies))}
    units=[]
    for team,arr in (('ally',allies),('enemy',enemies)):
        for idx,pkid in enumerate(arr):
            p=copy.deepcopy(app.state['pokemon'][pkid]);calc=computed(p)
            p.update({'pokemon_id':p.pop('id'),'id':eid(),'team':team,'trainer_id':p['owner'],'active':idx<slots[team],
                      'acted':False,'current_hp':clamp(int(p.get('current_hp',calc['max_hp'])),0,calc['max_hp']),
                      'status':p.get('status','none'),'status_turns':0,'temp_ac':{'physical':0,'special':0},'timed_mods':{},
                      'stages':{name:0 for name in STAGES}, 'protected':False,'initiative_roll':None,'initiative':10+calc['speed_mod'],
                      'mega_active':False,'tera_active':False,'participated':False,'revealed_moves':[],'bond_reroll_used':False})
            units.append(p)
    return {'id':eid(),'phase':'initiative','round':1,'weather':'none','terrain':'none','units':units,'order':[], 'turn_index':0, 'slots':slots,
            'used_transformations':{}, 'log':[{'when':now(),'round':1,'message':'Battle created. Enter initiative dice, then begin combat.'}], '_history':[]}

def legal_move_selection(p,selection):
    if not isinstance(selection,list) or not 1<=len(selection)<=4 or any(not isinstance(x,str) for x in selection):
        raise ValueError('Choose 1–4 moves')
    if len(set(selection))!=len(selection):raise ValueError('Choose unique moves')
    options={m['name']:m for m in p['allowed_moves'] if m['learned_at']<=p['level']}
    if any(m not in options for m in selection):raise ValueError('Move is not legal for the Pokémon’s current level')
    return options

def apply_move_selection(p,selection):
    options=legal_move_selection(p,selection)
    old={m['name']:m for m in p['moves']}
    p['moves']=[{**options[name], 'remaining_pp':old.get(name,options[name]).get('remaining_pp',options[name]['pp'])} for name in selection]
    p['move_learning_alert']=False

def verify_team_request(pid,party_ids):
    if not isinstance(party_ids,list) or len(party_ids)>6 or any(not isinstance(x,str) for x in party_ids):
        raise ValueError('Choose at most six Pokémon')
    if len(set(party_ids))!=len(party_ids):raise ValueError('A Pokémon cannot be selected twice')
    owned={p['id']:p for p in app.state['pokemon'].values() if p.get('owner')==pid}
    if any(x not in owned for x in party_ids):raise PermissionError('You can only choose your own Pokémon')
    return owned

def move_restricted_in_battle(pkids):
    battle=app.state.get('battle')
    return bool(has_active_battle() and any(u['pokemon_id'] in pkids for u in battle['units']))

def record_review(req,approve,reason=''):
    entry={**copy.deepcopy(req),'status':'approved' if approve else 'denied','decided_at':now()}
    if not approve and reason:entry['reason']=clean(reason,160)
    history=app.state.setdefault('change_history',[])
    history.append(entry)
    if len(history)>100:del history[:-100]

def has_team_request(pid):
    return any(r['player_id']==pid and r.get('kind','storage') in ('team','storage') for r in app.state['requests'])

def perform(who,action,d):
    s=app.state;b=s.get('battle');role=who['role'] if who else None
    if action=='player_nickname':
        require_player(who);p=s['pokemon'].get(d.get('id'))
        if not p or p['owner']!=who['id']:raise PermissionError('Pokémon is not yours')
        p['nickname']=clean(d.get('nickname'),35) or display(p['species'])
        return {'message':'Nickname updated'}
    if action in ('request_moves','player_moves'):
        if role!='dm':require_player(who)
        p=s['pokemon'].get(d.get('id'))
        if not p or (role!='dm' and p['owner']!=who['id']):raise PermissionError('Pokémon is not yours')
        selection=d.get('moves',[])
        legal_move_selection(p,selection)
        if move_restricted_in_battle({p['id']}):raise ValueError('Cannot change moves while this Pokémon is in an ongoing battle')
        if role=='dm':
            apply_move_selection(p,selection)
            return {'message':'DM updated Pokémon moves'}
        if any(r['player_id']==who['id'] and r.get('kind')=='moves' and r.get('pokemon_id')==p['id'] for r in s['requests']):
            raise ValueError('A move change is already waiting for DM approval')
        s['requests'].append({'id':eid(),'kind':'moves','player_id':who['id'],'pokemon_id':p['id'],'moves':selection,'when':now()})
        return {'message':'Move changes sent to the DM for approval'}
    if action=='request_team':
        require_player(who)
        party_ids=d.get('party_ids',[])
        owned=verify_team_request(who['id'],party_ids)
        if has_team_request(who['id']):raise ValueError('A team change is already waiting for the DM')
        current={p['id'] for p in owned.values() if p.get('slot')=='party'}
        if current==set(party_ids):raise ValueError('Your selected party is already active')
        s['requests'].append({'id':eid(),'kind':'team','player_id':who['id'],'party_ids':party_ids,'when':now()})
        return {'message':'Team changes sent to the DM for approval'}
    if action=='cancel_request':
        require_player(who)
        req=next((r for r in s['requests'] if r['id']==d.get('id') and r['player_id']==who['id']),None)
        if not req:raise ValueError('Your pending request was not found')
        s['requests'].remove(req)
        return {'message':'Request cancelled; your Pokémon were not changed'}
    if action=='request_storage':
        require_player(who);p=s['pokemon'].get(d.get('id'))
        if not p or p['owner']!=who['id']:raise PermissionError('Pokémon is not yours')
        slot=d.get('slot')
        if slot not in ('party','storage') or slot==p['slot']:raise ValueError('Choose a different destination')
        if has_team_request(who['id']):raise ValueError('A team change is already waiting for the DM')
        s['requests'].append({'id':eid(),'kind':'storage','player_id':who['id'],'pokemon_id':p['id'],'slot':slot,'when':now()})
        return {'message':'Party transfer sent to the DM for approval'}
    if action=='player_initiative':
        require_player(who)
        if not b or b['phase']!='initiative':raise ValueError('Not preparing initiative')
        u=unit_by_id(b,d.get('unit_id'))
        if u['trainer_id']!=who['id']:raise PermissionError('Not your Pokémon')
        u['initiative_roll']=toint(d.get('roll'),1,20);u['initiative']=u['initiative_roll']+computed(u)['speed_mod']
        return {'message':'Initiative recorded'}
    if action in ('attack','pass','switch','transform'):
        if role!='dm':require_player(who)
        if not b or b['phase']!='battle':raise ValueError('No active battle')
        a=active_actor(b)
        if role!='dm' and a['trainer_id']!=who['id']:raise PermissionError('It is another Trainer’s turn')
        if action=='attack':act_attack(who,b,d);return {'message':'Move resolved'}
        if action=='pass':checkpoint();a['acted']=True;append_log(b,f'{display(a["species"])} passed.');advance(b);return {'message':'Turn passed'}
        if action=='switch':
            reserve=unit_by_id(b,d.get('reserve_id'))
            if reserve['trainer_id']!=a['trainer_id'] or reserve['team']!=a['team'] or reserve['active'] or reserve['current_hp']<=0:raise ValueError('Choose a healthy bench Pokémon belonging to the same Trainer')
            checkpoint();a['active']=False;a['acted']=True;reserve['active']=True;reserve['acted']=True
            append_log(b,f'{display(a["species"])} switched out for {display(reserve["species"])}.')
            advance(b);return {'message':'Pokémon switched'}
        # Transformation does NOT consume the turn; per-Trainer resources are limited per battle.
        mode=d.get('mode')
        if mode not in ('mega','tera'):raise ValueError('Choose Mega or Tera')
        if a.get('mega_active') or a.get('tera_active'):raise ValueError('This Pokémon has already transformed')
        if not a.get(mode+'_enabled'):raise ValueError('The DM has not enabled this transformation for this Pokémon')
        owner=a.get('trainer_id') or ('dm-'+a['team']);uses=b['used_transformations'].setdefault(owner,{'mega':False,'tera':False})
        if uses.get(mode):raise ValueError('That Trainer has already used this transformation this battle')
        if mode=='mega':
            form=d.get('form')
            available=[m for m in a.get('mega_forms',[]) if isinstance(m,dict)]
            match=next((m for m in available if m.get('name')==form),None)
            if match is None or not isinstance(match.get('stats'),list) or len(match['stats'])!=6:raise ValueError('Load and select a valid Mega form first')
            checkpoint();oldmax=computed(a)['max_hp'];a['stats']=match['stats'];a['types']=match.get('types',a['types']);a['ability']=match.get('ability',a['ability']);a['mega_active']=True;a['species']=match['name'];a['dex_id']=match.get('dex_id',a['dex_id']);a['current_hp']=clamp(a['current_hp']+computed(a)['max_hp']-oldmax,1,computed(a)['max_hp'])
        else:
            if a.get('tera_type') not in TYPES:raise ValueError('No approved Tera type')
            checkpoint();a['tera_active']=True
        uses[mode]=True;append_log(b,f'{display(a["nickname"])} activated {"Mega Evolution" if mode=="mega" else "Terastallization"}!')
        return {'message':'Transformation activated'}
    require_dm(who)
    if action=='approve_player':
        p=s['players'].get(d.get('id'))
        if not p or p['state']!='pending':raise ValueError('Pending Trainer not found')
        if sum(x['state']=='approved' for x in s['players'].values())>=3:raise ValueError('Maximum of three Trainers reached')
        p['state']='approved';return {'message':'Trainer approved'}
    if action=='remove_player':
        pid=d.get('id')
        if pid not in s['players']:raise ValueError('Trainer not found')
        if any(p.get('owner')==pid for p in s['pokemon'].values()):raise ValueError('Reassign their Pokémon before removing this Trainer')
        del s['players'][pid];app.revoke_player(pid)
        s['requests']=[r for r in s['requests'] if r['player_id']!=pid]
        return {'message':'Trainer removed'}
    if action=='create_pokemon':
        mon=mon_card_from_input(d.get('pokemon',{}))
        s['pokemon'][mon['id']]=mon;return {'message':f'{display(mon["species"])} created'+(' (SHINY!)' if mon['shiny'] else ''),'pokemon_id':mon['id']}
    if action=='edit_pokemon':
        p=s['pokemon'].get(d.get('id'))
        if not p:raise ValueError('Pokémon not found')
        if has_active_battle() and any(u['pokemon_id']==p['id'] for u in b['units']):raise ValueError('Edit battle stats from the DM battle controls while in combat')
        if 'owner' in d:
            owner=d['owner'];owner=owner if owner in s['players'] and s['players'][owner]['state']=='approved' else None
            if owner and owner!=p['owner'] and p['slot']=='party' and sum(x['owner']==owner and x['slot']=='party' for x in s['pokemon'].values())>=6:
                p['slot']='storage'
            p['owner']=owner
            if p['owner'] is None:p['slot']='storage'
        if 'level' in d:
            oldmax=computed(p)['max_hp'];p['level']=toint(d['level'],1,100);p['current_hp']=clamp(p['current_hp']+computed(p)['max_hp']-oldmax,0,computed(p)['max_hp'])
        if 'experience' in d:p['experience']=toint(d['experience'],0,99999999)
        if 'current_hp' in d:p['current_hp']=toint(d['current_hp'],0,computed(p)['max_hp'])
        if 'status' in d:
            if d['status'] not in ALLOWED_STATUS:raise ValueError('Unknown status')
            p['status']=d['status']
        if 'bond_points' in d:p['bond_points']=toint(d['bond_points'],0,20)
        if 'shiny' in d:p['shiny']=bool(d['shiny'])
        if 'legend_ac' in d:p['legend_ac']=bool(d['legend_ac'] and p['legendary'])
        if 'tera_enabled' in d:p['tera_enabled']=bool(d['tera_enabled'])
        if 'mega_enabled' in d:p['mega_enabled']=bool(d['mega_enabled'])
        if 'tera_type' in d and d['tera_type'] in TYPES:p['tera_type']=d['tera_type']
        if 'nickname' in d:p['nickname']=clean(d['nickname'])
        if 'slot' in d:
            slot=d['slot'];
            if slot not in ('party','storage'):raise ValueError('Unknown storage slot')
            if slot=='party' and p['owner'] and sum(x['owner']==p['owner'] and x['slot']=='party' and x['id']!=p['id'] for x in s['pokemon'].values())>=6:raise ValueError('Trainer party is full')
            p['slot']=slot
        return {'message':'Pokémon updated'}
    if action=='dm_award_xp':
        p=s['pokemon'].get(d.get('id'))
        if not p:raise ValueError('Pokémon not found')
        if has_active_battle() and any(u['pokemon_id']==p['id'] for u in b['units']):raise ValueError('Award manual EXP after the battle')
        levels=award_exp(p,toint(d.get('amount'),0,100000))
        return {'message':f'EXP awarded'+(f' — {levels} level(s) gained!' if levels else '')}
    if action=='evolve_pokemon':
        p=s['pokemon'].get(d.get('id'))
        if not p:raise ValueError('Pokémon not found')
        if has_active_battle() and any(u['pokemon_id']==p['id'] for u in b['units']):raise ValueError('Evolve after the battle')
        data=d.get('new_form',{});base=mon_card_from_input({**data,'owner':p['owner'],'level':p['level']})
        oldmax=computed(p)['max_hp'];oldhp=p['current_hp'];oldmoves=p['moves'];legal={m['name']:m for m in base['allowed_moves']}
        # Previously learned moves are retained on evolution even when the
        # evolved species' level-up list differs. This matches v1.3 behavior.
        for old in oldmoves:
            if old['name'] not in legal:legal[old['name']]={**old, 'learned_at':0}
        for k in ('species','dex_id','stats','types','base_types','ability','abilities','legendary','mega_forms'):
            p[k]=base[k]
        p['allowed_moves']=list(legal.values())
        p['moves']=[{**legal[m['name']],'remaining_pp':m['remaining_pp']} for m in oldmoves][:4] or base['moves']
        p['current_hp']=clamp(oldhp+computed(p)['max_hp']-oldmax,0,computed(p)['max_hp'])
        return {'message':'Pokémon evolved; existing Bond, EXP, shiny, and eligible moves preserved'}
    if action=='delete_pokemon':
        pkid=d.get('id')
        if pkid not in s['pokemon']:raise ValueError('Pokémon not found')
        if has_active_battle() and any(u['pokemon_id']==pkid for u in b['units']):raise ValueError('End battle first')
        del s['pokemon'][pkid];s['requests']=[r for r in s['requests'] if r['pokemon_id']!=pkid]
        return {'message':'Pokémon deleted'}
    if action in ('storage_response','review_change'):
        r=next((r for r in s['requests'] if r['id']==d.get('id')),None)
        if not r:raise ValueError('Request not found')
        approve=d.get('approve') is True
        kind=r.get('kind','storage')
        if approve:
            if kind=='moves':
                p=s['pokemon'].get(r['pokemon_id'])
                if not p or p.get('owner')!=r['player_id']:raise ValueError('Pokémon ownership changed; reject this request')
                if move_restricted_in_battle({p['id']}):raise ValueError('Wait until the Pokémon’s battle ends')
                apply_move_selection(p,r['moves'])
            elif kind=='team':
                owned=verify_team_request(r['player_id'],r['party_ids'])
                if move_restricted_in_battle(set(owned)):raise ValueError('Wait until the Trainer’s battle ends to change their party')
                chosen=set(r['party_ids'])
                for mon in owned.values():
                    mon['slot']='party' if mon['id'] in chosen else 'storage'
                    if mon['id'] in chosen:mon['party_order']=r['party_ids'].index(mon['id'])
            elif kind=='storage':
                p=s['pokemon'].get(r['pokemon_id'])
                if not p or p.get('owner')!=r['player_id']:raise ValueError('Ownership changed; reject this request')
                if move_restricted_in_battle({p['id']}):raise ValueError('Wait until the Pokémon’s battle ends')
                if r['slot']=='party' and sum(x['owner']==r['player_id'] and x['slot']=='party' and x['id']!=p['id'] for x in s['pokemon'].values())>=6:
                    raise ValueError('Trainer party already has six Pokémon; request a complete team swap instead')
                p['slot']=r['slot']
            else:raise ValueError('Unknown request type')
        record_review(r,approve,d.get('reason',''))
        s['requests'].remove(r)
        return {'message':'Change approved and applied' if approve else 'Change denied — Pokémon unchanged'}
    if action=='start_battle':
        if has_active_battle():raise ValueError('Finish the current battle first')
        s['battle']=new_battle(d);return {'message':'Battle setup created'}
    if action=='dm_initiative':
        if not b or b['phase']!='initiative':raise ValueError('Not preparing initiative')
        u=unit_by_id(b,d.get('unit_id'));u['initiative_roll']=toint(d['roll'],1,20);u['initiative']=u['initiative_roll']+computed(u)['speed_mod']
        return {'message':'Initiative saved'}
    if action=='begin_battle':
        if not b or b['phase']!='initiative':raise ValueError('Not in initiative setup')
        b['order']=[u['id'] for u in sorted(b['units'],key=lambda u:(-u['initiative'],-computed(u)['speed_mod'],u['id']))]
        b['phase']='battle';b['turn_index']=0;advance(b);append_log(b,'Combat begins!')
        return {'message':'Combat started'}
    if action=='dm_override':
        if not b or b['phase'] not in ('battle','initiative'):raise ValueError('No battle to edit')
        u=unit_by_id(b,d['unit_id']);key=d.get('kind');val=d.get('value'); checkpoint()
        if key=='hp':u['current_hp']=toint(val,0,computed(u)['max_hp'])
        elif key=='damage':u['current_hp']=max(0,u['current_hp']-toint(val,0,100000))
        elif key=='heal':u['current_hp']=min(computed(u)['max_hp'],u['current_hp']+toint(val,0,100000))
        elif key=='status':
            if val not in ALLOWED_STATUS:raise ValueError('Invalid status')
            u['status']=val;u['status_turns']=random.randint(1,3) if val=='sleep' else 0
        elif key in ('physical','special'):
            u['temp_ac'][key]=toint(val,-15,15)
            duration=toint(d.get('duration',0),0,99)
            if duration:u['timed_mods'][key]=duration
            else:u['timed_mods'].pop(key,None)
        elif key in STAGES:
            u['stages'][key]=toint(val,-6,6)
            duration=toint(d.get('duration',0),0,99)
            if duration:u['timed_mods'][key]=duration
            else:u['timed_mods'].pop(key,None)
        elif key=='initiative':
            u['initiative']=toint(val,-20,100)
            if b['phase']=='battle':
                curr=active_actor(b)['id'];b['order']=[x['id'] for x in sorted(b['units'],key=lambda x:-x['initiative'])];b['turn_index']=b['order'].index(curr)
        elif key=='active':
            active=bool(val=='true');u['active']=active;u['acted']=True if active else u['acted']
        else:raise ValueError('Unknown DM override')
        update_mon_hp(u);append_log(b,f'DM adjusted {display(u["species"])}: {key} → {val}.')
        return {'message':'DM override applied'}
    if action=='dm_weather':
        if not b:raise ValueError('No battle')
        if d.get('weather') not in WEATHERS or d.get('terrain') not in TERRAINS:raise ValueError('Invalid weather or terrain')
        checkpoint();b['weather']=d['weather'];b['terrain']=d['terrain'];append_log(b,'The battlefield conditions changed.')
        return {'message':'Weather and terrain changed'}
    if action=='end_battle':
        if not b:raise ValueError('No battle to end')
        checkpoint();b['phase']='finished';append_log(b,'DM ended battle. HP and PP saved to Pokémon library.')
        return {'message':'Battle finished'}
    if action=='undo':
        if not b or not b.get('_history'):raise ValueError('Nothing to undo')
        snap=b['_history'].pop();hist=b['_history'];s['pokemon']=snap['pokemon'];s['battle']=snap['battle'];s['battle']['_history']=hist
        return {'message':'Previous battle action restored'}
    if action=='reset_battle':
        if b and b['phase']!='finished':raise ValueError('End the current battle before clearing it')
        s['battle']=None;return {'message':'Battle board cleared'}
    if action=='backup':
        fname=app.backup();return {'message':'Backup saved to data/backups/'+fname}
    raise ValueError('Unknown action')

class Handler(BaseHTTPRequestHandler):
    server_version='AveloraLAN/1.0'
    protocol_version='HTTP/1.1'
    def log_message(self,fmt,*args):
        # Avoid logging cookies or player details in terminal logs.
        if '/api/events' not in self.path:super().log_message(fmt,*args)
    def is_host(self):
        return self.client_address[0] in ('127.0.0.1','::1')
    def cookie_token(self):
        cookies=SimpleCookie()
        try:cookies.load(self.headers.get('Cookie',''))
        except Exception:return ''
        return cookies.get(COOKIE_NAME).value if cookies.get(COOKIE_NAME) else ''
    def json_response(self,obj,status=200,extra=None):
        data=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def static_response(self,path):
        file=(ROOT/'static'/path)
        if path not in ('index.html','app.js','style.css') or not file.exists():return self.json_response({'error':'Not found'},404)
        data=file.read_bytes();mt='text/html' if path.endswith('html') else 'text/css' if path.endswith('.css') else 'application/javascript'
        self.send_response(200);self.send_header('Content-Type',mt+'; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self' https://pokeapi.co; img-src 'self' https://raw.githubusercontent.com https://raw.githubusercontent.com:443 data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'") if path=='index.html' else None
        self.end_headers();self.wfile.write(data)
    def parse_json(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON request required')
        n=int(self.headers.get('Content-Length','0'))
        if n<=0 or n>200000:raise ValueError('Invalid request size')
        return json.loads(self.rfile.read(n))
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path)
        path=parsed.path
        if path=='/healthz':return self.json_response({'status':'ok'})
        if path in ('/','/index.html'):return self.static_response('index.html')
        if path in ('/app.js','/style.css'):return self.static_response(path[1:])
        if path=='/api/offline':
            return self.json_response({'pokemon':BASE_POKE,'moves':__import__('rules').MOVE_DB,'move_types':__import__('rules').MOVE_TYPES,'offline':True})
        if path=='/api/session':
            with app.lock:
                who=app.user(self.cookie_token());out=projection(who)
                if not who:out['host_login']=ONLINE or self.is_host()
                return self.json_response(out)
        if path=='/api/events':
            with app.lock:
                who=app.user(self.cookie_token())
                if not who:return self.json_response({'error':'Not logged in'},401)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-store');self.send_header('Connection','keep-alive');self.end_headers()
            try:
                last=-1
                while True:
                    with app.condition:
                        v=app.state['version']
                        if last==v:app.condition.wait(timeout=12)
                        v=app.state['version']
                    if v!=last:self.wfile.write(f'event: version\ndata: {v}\n\n'.encode());last=v
                    else:self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,TimeoutError,OSError):pass
            return
        if path=='/api/backup.json':
            with app.lock:
                who=app.user(self.cookie_token())
                if not who or who['role']!='dm':return self.json_response({'error':'DM access required'},403)
                # Export only content, not private session tokens.
                obj={k:copy.deepcopy(v) for k,v in app.state.items() if k not in ('battle',)}
                if app.state.get('battle'):obj['battle']={k:copy.deepcopy(v) for k,v in app.state['battle'].items() if k!='_history'}
                payload=json.dumps(obj,ensure_ascii=False,indent=2).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Disposition','attachment; filename="avelora_campaign_backup.json"');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
        self.json_response({'error':'Not found'},404)
    def do_POST(self):
        origin=self.headers.get('Origin')
        expected=f"{'https' if ONLINE else 'http'}://{self.headers.get('Host','')}"
        if ONLINE and not origin:return self.json_response({'error':'Origin header is required'},403)
        if origin and origin!=expected:return self.json_response({'error':'Cross-origin requests are not permitted'},403)
        if ONLINE and self.headers.get('Sec-Fetch-Site','same-origin') not in ('same-origin','none'):
            return self.json_response({'error':'Cross-site request blocked'},403)
        path=urllib.parse.urlparse(self.path).path
        try:
            d=self.parse_json()
            with app.lock:
                if path=='/api/host_login':
                    if ONLINE:
                        throttle(self.client_address[0])
                        if not authenticated_dm(d.get('password','')):
                            failed(self.client_address[0]);raise PermissionError('Incorrect DM password')
                    elif not self.is_host():
                        raise PermissionError('DM sign-in is only allowed on the host computer')
                    token=app.create_session('dm')
                    return self.json_response({'ok':True},extra={'Set-Cookie':f'{COOKIE_NAME}={token}{COOKIE_FLAGS}; Max-Age=2592000'})
                if path=='/api/join':
                    if ONLINE:throttle(self.client_address[0])
                    if d.get('code','').strip().upper()!=app.state['room_code']:
                        if ONLINE:failed(self.client_address[0])
                        raise PermissionError('Incorrect room code')
                    nick=clean(d.get('nickname'),28)
                    if len(nick)<2:raise ValueError('Trainer name must be at least two characters')
                    if sum(p['state']=='approved' for p in app.state['players'].values())>=3:raise ValueError('The campaign already has three approved players')
                    if sum(p['state']=='pending' for p in app.state['players'].values())>=8:raise ValueError('Too many pending requests; ask the DM to clear them')
                    pid=eid();app.state['players'][pid]={'id':pid,'nickname':nick,'state':'pending','joined':now()}
                    token=app.create_session('player',pid);app.changed()
                    return self.json_response({'ok':True,'pending':True},extra={'Set-Cookie':f'{COOKIE_NAME}={token}{COOKIE_FLAGS}; Max-Age=15552000'})
                who=app.user(self.cookie_token())
                if path=='/api/logout':
                    import hashlib
                    tok=self.cookie_token()
                    if tok:app.db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(tok.encode()).hexdigest(),));app.db.commit()
                    return self.json_response({'ok':True},extra={'Set-Cookie':f'{COOKIE_NAME}={COOKIE_FLAGS}; Max-Age=0'})
                if not who:raise PermissionError('Join or sign in first')
                if path=='/api/action':
                    out=perform(who,d.get('action'),d.get('payload',{}));app.changed();return self.json_response({'ok':True,**out})
                raise ValueError('Unknown request')
        except PermissionError as e:self.json_response({'error':str(e)},403)
        except (ValueError,KeyError,TypeError,IndexError) as e:self.json_response({'error':str(e)},400)
        except Exception as e:
            print('Unexpected server exception:');traceback.print_exc()
            self.json_response({'error':'Unexpected server error; see hosting logs'},500)
    def do_OPTIONS(self):self.send_response(405);self.send_header('Content-Length','0');self.end_headers()

def guess_ips():
    ips=set()
    # No external request; UDP connect determines the route without transmitting data.
    try:
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.connect(('192.0.2.1',80));ips.add(sock.getsockname()[0]);sock.close()
    except OSError:pass
    try:
        for row in socket.getaddrinfo(socket.gethostname(),0,socket.AF_INET):
            ip=row[4][0]
            if not ip.startswith('127.'):ips.add(ip)
    except OSError:pass
    return sorted(ips)

def start(port,open_browser=True):
    # One instance: SQLite and in-process event signals are authoritative.
    srv=ThreadingHTTPServer(('0.0.0.0',port),Handler);srv.daemon_threads=True
    port=srv.server_address[1]
    if ONLINE:
        print(f'Avelora online server listening on port {port}. Data path: {DATA}')
        print('DM login is password protected; room code is visible only within the DM dashboard.')
    else:
        print(f'Avelora local server at http://localhost:{port}')
        print('Room code:',app.state['room_code'])
    if open_browser:
        import webbrowser
        threading.Timer(0.6,lambda:webbrowser.open(f'http://localhost:{port}')).start()
    if ONLINE:
        def stop_server(signum,frame):
            threading.Thread(target=srv.shutdown,daemon=True).start()
        signal.signal(signal.SIGTERM,stop_server)
    try:srv.serve_forever(poll_interval=.4)
    except KeyboardInterrupt:print('\nStopping Avelora...')
    finally:
        srv.server_close()
        with app.lock:app.persist();app.backup();app.db.close()
        print('Campaign safely saved. See you next session!')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8080' if ONLINE else '8765')));parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args();start(args.port,not args.no_browser)
