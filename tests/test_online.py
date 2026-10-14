"""Run with: python -m unittest discover -s tests -v
Tests internet-deployed mode over a local HTTP socket with HTTPS Origin and cookies
manually supplied to simulate Railway's HTTPS reverse proxy.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

BASE = Path(__file__).resolve().parents[1]
PASSWORD='test_password_that_is_secure_123'

def free_port():
    s=socket.socket();s.bind(('127.0.0.1',0));n=s.getsockname()[1];s.close();return n

class CloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.port=free_port()
        env={**os.environ,'PORT':str(cls.port),'AVELORA_ONLINE':'1','AVELORA_DM_PASSWORD':PASSWORD,'AVELORA_DATA_DIR':cls.temp.name}
        cls.proc=subprocess.Popen(['python','server.py','--no-browser'],cwd=BASE,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        for _ in range(80):
            try:
                cls.req('/healthz');break
            except Exception:
                time.sleep(.1)
        else:
            cls.proc.terminate();raise RuntimeError('Server did not start')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:cls.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:cls.proc.kill();cls.proc.wait()
        cls.proc.stdout.close();cls.temp.cleanup()
    @classmethod
    def req(cls,path,payload=None,cookie=None,origin=True):
        con=http.client.HTTPConnection('127.0.0.1',cls.port,timeout=6)
        headers={'Host':f'127.0.0.1:{cls.port}'}
        if payload is not None:
            headers['Content-Type']='application/json'
            if origin:headers['Origin']=f'https://127.0.0.1:{cls.port}'
        if cookie:headers['Cookie']=cookie
        con.request('POST' if payload is not None else 'GET',path,body=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        res=con.getresponse();blob=res.read();status=res.status;setcookie=res.getheader('Set-Cookie')
        con.close()
        return status,json.loads(blob),setcookie
    def test_online_multiuser(self):
        status,body,_=self.req('/api/session')
        self.assertEqual(status,200);self.assertTrue(body['online']);self.assertTrue(body['host_login'])
        status,body,_=self.req('/api/host_login',{'password':PASSWORD},origin=False)
        self.assertEqual(status,403)
        status,body,_=self.req('/api/host_login',{'password':'wrong-password'})
        self.assertEqual(status,403)
        status,body,cookie=self.req('/api/host_login',{'password':PASSWORD})
        self.assertEqual(status,200);self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie)
        dm_cookie=cookie.split(';')[0]
        status,dm,_=self.req('/api/session',cookie=dm_cookie)
        self.assertEqual(dm['role'],'dm');code=dm['room_code']
        players=[]
        for i in range(10):
            status,body,cookie=self.req('/api/join',{'code':code,'nickname':f'Player {i+1}'})
            self.assertEqual(status,200)
            pc=cookie.split(';')[0];players.append(pc)
            status,pending,_=self.req('/api/session',cookie=pc)
            self.assertTrue(pending['pending'])
        status,dm,_=self.req('/api/session',cookie=dm_cookie)
        for p in dm['players']:
            status,reply,_=self.req('/api/action',{'action':'approve_player','payload':{'id':p['id']}},dm_cookie)
            self.assertEqual(status,200)
        status,bad,_=self.req('/api/action',{'action':'approve_player','payload':{'id':dm['players'][0]['id']}},players[0]);self.assertEqual(status,403)
        status,full,_=self.req('/api/join',{'code':code,'nickname':'Extra'})
        self.assertEqual(status,400)
        ids=[]
        for species,owner in [('shinx',dm['players'][0]['id']),('pidgey',None)]:
            mon={'species':species,'level':5,'stats':[45,65,34,40,34,45] if species=='shinx' else [40,45,40,35,35,56],
                 'types':['electric'] if species=='shinx' else ['normal','flying'],'dex_id':403 if species=='shinx' else 16,
                 'owner':owner,'ability':'intimidate','allowed_moves':[{'name':'tackle','type':'normal','category':'physical','power':40,'accuracy':100,'pp':35,'learned_at':1}]}
            status,r,_=self.req('/api/action',{'action':'create_pokemon','payload':{'pokemon':mon}},dm_cookie)
            self.assertEqual(status,200,r);ids.append(r['pokemon_id'])
        status,view,_=self.req('/api/session',cookie=players[0]);self.assertEqual(len(view['pokemon']),1)
        status,view2,_=self.req('/api/session',cookie=players[1]);self.assertEqual(len(view2['pokemon']),0)
        status,view10,_=self.req('/api/session',cookie=players[9]);self.assertEqual(view10['role'],'player');self.assertEqual(len(view10['pokemon']),0)
        status,no10,_=self.req('/api/action',{'action':'player_nickname','payload':{'id':ids[0],'nickname':'Not Mine'}},players[9]);self.assertEqual(status,403)
        status,no,_=self.req('/api/action',{'action':'player_nickname','payload':{'id':ids[0],'nickname':'Hacked'}},players[1]);self.assertEqual(status,403)
        status,r,_=self.req('/api/action',{'action':'start_battle','payload':{'allies':[ids[0]],'enemies':[ids[1]]}},dm_cookie)
        self.assertEqual(status,200,r)
        status,pb,_=self.req('/api/session',cookie=players[0]);self.assertEqual(len(pb['battle']['units']),2)
        enemy=next(u for u in pb['battle']['units'] if u['team']=='enemy')
        self.assertNotIn('current_hp',enemy);self.assertNotIn('stats',enemy);self.assertNotIn('moves',enemy);self.assertNotIn('calculated',enemy)
        status,by,_=self.req('/api/backup.json',cookie=players[0]);self.assertEqual(status,403)
        status,by,_=self.req('/api/backup.json',cookie=dm_cookie);self.assertEqual(status,200)
        # Simulate battle roll, verify player can't issue DM overrides.
        status,deny,_=self.req('/api/action',{'action':'dm_override','payload':{'unit_id':enemy['id'],'kind':'hp','value':1}},players[0]);self.assertEqual(status,403)
        # Persistence test: SQLite contains committed state.
        import sqlite3
        db=sqlite3.connect(Path(self.temp.name)/'avelora.sqlite3')
        row=db.execute('SELECT data FROM saved WHERE id=1').fetchone();db.close()
        saved=json.loads(row[0]);self.assertEqual(len(saved['players']),10);self.assertEqual(len(saved['pokemon']),2)
        # Approval queue: players must not directly edit moves or party membership.
        extra={'species':'treecko','level':5,'stats':[40,45,35,65,55,70],
               'types':['grass'],'dex_id':252,'owner':dm['players'][0]['id'],'ability':'overgrow',
               'allowed_moves':[{'name':'pound','type':'normal','category':'physical','power':40,'accuracy':100,'pp':35,'learned_at':1},
                                {'name':'absorb','type':'grass','category':'special','power':20,'accuracy':100,'pp':25,'learned_at':5}]}
        status,created,_=self.req('/api/action',{'action':'create_pokemon','payload':{'pokemon':extra}},dm_cookie)
        self.assertEqual(status,200,created);extra_id=created['pokemon_id']
        status,before,_=self.req('/api/session',cookie=players[0]);original=next(p for p in before['pokemon'] if p['id']==extra_id)
        self.assertEqual(original['slot'],'party')
        new_moves=['absorb'] if original['moves'][0]['name']!='absorb' else ['pound']
        status,forbidden,_=self.req('/api/action',{'action':'request_moves','payload':{'id':extra_id,'moves':new_moves}},players[1])
        self.assertEqual(status,403)
        status,changed,_=self.req('/api/action',{'action':'request_moves','payload':{'id':extra_id,'moves':new_moves}},players[0])
        self.assertEqual(status,200,changed)
        status,duplicate,_=self.req('/api/action',{'action':'request_moves','payload':{'id':extra_id,'moves':new_moves}},players[0])
        self.assertEqual(status,400)
        status,before_review,_=self.req('/api/session',cookie=players[0])
        self.assertEqual(next(p for p in before_review['pokemon'] if p['id']==extra_id)['moves'],original['moves'])
        move_req=next(r for r in before_review['requests'] if r['kind']=='moves')
        status,access,_=self.req('/api/action',{'action':'review_change','payload':{'id':move_req['id'],'approve':True}},players[0])
        self.assertEqual(status,403)
        status,approval,_=self.req('/api/action',{'action':'review_change','payload':{'id':move_req['id'],'approve':True}},dm_cookie)
        self.assertEqual(status,200,approval)
        status,after_review,_=self.req('/api/session',cookie=players[0])
        self.assertEqual([m['name'] for m in next(p for p in after_review['pokemon'] if p['id']==extra_id)['moves']],new_moves)
        self.assertTrue(any(r['kind']=='moves' and r['status']=='approved' for r in after_review['change_history']))
        # A DM must approve an entire party swap as a single change.
        status,team,_=self.req('/api/action',{'action':'request_team','payload':{'party_ids':[ids[0]]}},players[0]);self.assertEqual(status,200,team)
        status,dmview,_=self.req('/api/session',cookie=dm_cookie)
        team_req=next(r for r in dmview['requests'] if r['kind']=='team')
        status,other,_=self.req('/api/session',cookie=players[1]);self.assertFalse(other['requests']);self.assertFalse(other['change_history'])
        # Can't approve a roster change mid-battle.
        status,blocked,_=self.req('/api/action',{'action':'review_change','payload':{'id':team_req['id'],'approve':True}},dm_cookie)
        self.assertEqual(status,400,blocked)
        status,end,_=self.req('/api/action',{'action':'end_battle','payload':{}},dm_cookie);self.assertEqual(status,200,end)
        status,approved,_=self.req('/api/action',{'action':'review_change','payload':{'id':team_req['id'],'approve':True}},dm_cookie)
        self.assertEqual(status,200,approved)
        status,pstate,_=self.req('/api/session',cookie=players[0]);self.assertEqual(next(p for p in pstate['pokemon'] if p['id']==extra_id)['slot'],'storage')
        status,denied_req,_=self.req('/api/action',{'action':'request_team','payload':{'party_ids':[extra_id]}},players[0]);self.assertEqual(status,200,denied_req)
        status,pstate,_=self.req('/api/session',cookie=players[0]);r=pstate['requests'][0]
        status,denied,_=self.req('/api/action',{'action':'review_change','payload':{'id':r['id'],'approve':False,'reason':'Check with the DM first'}},dm_cookie)
        self.assertEqual(status,200,denied)
        status,pstate,_=self.req('/api/session',cookie=players[0]);self.assertEqual(next(p for p in pstate['pokemon'] if p['id']==extra_id)['slot'],'storage')
        self.assertEqual(pstate['change_history'][-1]['status'],'denied')
        self.assertIn('Check with the DM',pstate['change_history'][-1]['reason'])
        # Players can retract their own pending changes; not anyone else's.
        status,new_req,_=self.req('/api/action',{'action':'request_moves','payload':{'id':extra_id,'moves':['pound']}},players[0])
        self.assertEqual(status,200,new_req)
        status,pview,_=self.req('/api/session',cookie=players[0]);req_id=pview['requests'][0]['id']
        status,forbidden,_=self.req('/api/action',{'action':'cancel_request','payload':{'id':req_id}},players[1]);self.assertEqual(status,400)
        status,ok,_=self.req('/api/action',{'action':'cancel_request','payload':{'id':req_id}},players[0]);self.assertEqual(status,200,ok)
        status,pview,_=self.req('/api/session',cookie=players[0]);self.assertFalse(pview['requests'])
        status,not_owner,_=self.req('/api/action',{'action':'request_team','payload':{'party_ids':[ids[1]]}},players[0]);self.assertEqual(status,403)
        status,too_many,_=self.req('/api/action',{'action':'request_team','payload':{'party_ids':[extra_id]*7}},players[0]);self.assertEqual(status,400)

if __name__=='__main__':unittest.main()
