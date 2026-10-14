"""Battle QOL integration: privacy, dice totals, swapping and bulk deletion."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import http.client
import unittest

ROOT=Path(__file__).resolve().parents[1]
PASS='integration_password_sufficiently_long_654'

class BattleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        s=socket.socket();s.bind(('127.0.0.1',0));cls.port=s.getsockname()[1];s.close()
        env={**os.environ,'PORT':str(cls.port),'AVELORA_DM_PASSWORD':PASS,'AVELORA_ONLINE':'1','AVELORA_DATA_DIR':cls.tmp.name}
        cls.proc=subprocess.Popen(['python','server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                st,_,_=cls.request('/healthz')
                if st==200:break
            except Exception:time.sleep(.08)
        else:raise RuntimeError('Test server failed to start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.wait(timeout=3);cls.proc.stdout.close();cls.tmp.cleanup()

    @classmethod
    def request(cls,path,payload=None,cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1',cls.port,timeout=4)
        headers={'Host':f'127.0.0.1:{cls.port}'}
        if cookie:headers['Cookie']=cookie
        if payload is not None:headers.update({'Content-Type':'application/json','Origin':f'https://127.0.0.1:{cls.port}'})
        conn.request('POST' if payload is not None else 'GET',path,json.dumps(payload) if payload is not None else None,headers)
        result=conn.getresponse();status=result.status;cookie_out=result.getheader('Set-Cookie');body=json.loads(result.read());conn.close();return status,body,cookie_out

    @classmethod
    def do(cls,cookie,action,**args):return cls.request('/api/action',{'action':action,'payload':args},cookie)

    def test_multiplayer_battle_and_registrar(self):
        status,_,dm_cookie=self.request('/api/host_login',{'password':PASS});self.assertEqual(status,200)
        dm_cookie=dm_cookie.split(';')[0]
        _,dm,_=self.request('/api/session',cookie=dm_cookie)
        status,_,pc=self.request('/api/join',{'code':dm['room_code'],'nickname':'Testing Trainer'});self.assertEqual(status,200)
        pc=pc.split(';')[0]
        _,dm,_=self.request('/api/session',cookie=dm_cookie)
        trainer=dm['players'][0]['id']
        self.assertEqual(self.do(dm_cookie,'approve_player',id=trainer)[0],200)
        ids=[]
        for species,owner in [('shinx',trainer),('luxio',trainer),('pidgey',None),('caterpie',None),('rattata',None)]:
            mon={'species':species,'level':10,'stats':[80,80,80,80,80,80],'types':['normal'],'dex_id':16,'owner':owner,'ability':'keen-eye',
                'allowed_moves':[{'name':'tackle','type':'normal','category':'physical','power':40,'accuracy':100,'pp':35,'learned_at':1}]}
            status,body,_=self.do(dm_cookie,'create_pokemon',pokemon=mon)
            self.assertEqual(status,200,body);ids.append(body['pokemon_id'])
        self.assertEqual(self.do(dm_cookie,'start_battle',allies=ids[:2],enemies=ids[2:4],ally_slots=1,enemy_slots=1)[0],200)
        _,pb,_=self.request('/api/session',cookie=pc)
        self.assertEqual(len(pb['battle']['units']),3)
        self.assertNotIn('caterpie',json.dumps(pb['battle']).lower())
        _,full,_=self.request('/api/session',cookie=dm_cookie)
        self.assertEqual(len(full['battle']['units']),4)
        hidden=next(u for u in full['battle']['units'] if u['pokemon_id']==ids[3])
        self.assertEqual(self.do(dm_cookie,'dm_override',unit_id=hidden['id'],kind='status',value='burn')[0],200)
        _,hidden_view,_=self.request('/api/session',cookie=pc)
        self.assertNotIn('caterpie',json.dumps(hidden_view['battle']).lower())
        self.assertEqual(self.do(pc,'player_initiative',unit_id=pb['battle']['units'][0]['id'],roll=125)[0],200)
        _,pb,_=self.request('/api/session',cookie=pc)
        self.assertEqual(pb['battle']['units'][0]['initiative_roll'],125)
        self.assertEqual(self.do(dm_cookie,'begin_battle')[0],200)
        _,pb,_=self.request('/api/session',cookie=pc)
        actor=next(u for u in pb['battle']['units'] if u['pokemon_id']==ids[0])
        reserve=next(u for u in pb['battle']['units'] if u['pokemon_id']==ids[1])
        self.assertEqual(self.do(pc,'switch',reserve_id=reserve['id'])[0],200)
        _,pb,_=self.request('/api/session',cookie=pc)
        self.assertFalse(next(u for u in pb['battle']['units'] if u['id']==actor['id'])['active'])
        self.assertTrue(next(u for u in pb['battle']['units'] if u['id']==reserve['id'])['active'])
        # Faint the switched-in Pokémon and replace it with a healthy reserve.
        self.assertEqual(self.do(dm_cookie,'dm_override',unit_id=reserve['id'],kind='hp',value=0)[0],200)
        self.assertEqual(self.do(pc,'replace_fainted',fainted_id=reserve['id'],reserve_id=actor['id'])[0],200)
        _,pb,_=self.request('/api/session',cookie=pc)
        self.assertTrue(next(u for u in pb['battle']['units'] if u['id']==actor['id'])['active'])
        self.assertFalse(next(u for u in pb['battle']['units'] if u['id']==reserve['id'])['active'])
        # Large physical dice sums should no longer be rejected as impossible.
        # Current actor may be NPC; the DM is authorized to submit an attack.
        _,db,_=self.request('/api/session',cookie=dm_cookie)
        bid=db['battle'];current=next(u for u in bid['units'] if u['id']==bid['order'][bid['turn_index']])
        opposing=next(u for u in bid['units'] if u['active'] and u['current_hp']>0 and u['team']!=current['team'])
        status,body,_=self.do(dm_cookie,'attack',move_index=0,targets=[{'target_id':opposing['id'],'d20':20,'dice_sum':50000}])
        self.assertEqual(status,200,body)
        # Players may not mass-delete; DM cannot bulk-delete Pokémon in combat.
        self.assertEqual(self.do(pc,'bulk_delete_pokemon',ids=[ids[4]])[0],403)
        self.assertEqual(self.do(dm_cookie,'bulk_delete_pokemon',ids=[ids[0]])[0],400)
        self.assertEqual(self.do(dm_cookie,'end_battle')[0],200)
        self.assertEqual(self.do(dm_cookie,'bulk_delete_pokemon',ids=[ids[2],ids[3],ids[4]])[0],200)
        _,dm,_=self.request('/api/session',cookie=dm_cookie)
        self.assertEqual(len(dm['pokemon']),2)
        self.assertEqual(self.do(dm_cookie,'dm_initiative',unit_id=actor['id'],roll=123)[0],400)  # closed phase
