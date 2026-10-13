"""Avelora homebrew rules carried forward from Combat Manager v1.3.

Only the server uses this module to resolve combat; clients never dictate damage,
AC, ownership, Pokémon levels, transformation eligibility or EXP awards.
"""
import math, json, random
from pathlib import Path

OFFLINE = json.loads((Path(__file__).parent / 'offline_data.json').read_text())
TYPE_CHART = OFFLINE['TYPE_CHART']
BASE_POKE = OFFLINE['OFFLINE']
MOVE_DB = OFFLINE['OFFLINE_MOVES']
MOVE_TYPES = OFFLINE['MOVE_TYPES']


def clamp(x, lo, hi): return max(lo, min(hi, x))
def rnd(x): return math.floor(x + .5)

def computed(p):
    level = int(p.get('level', 5)); stats = p.get('stats', [50]*6)
    steps = (level-1)//5
    attrs = [clamp(8+rnd(v/8)+steps, 1, 40) for v in stats]
    cha = clamp(10+steps+clamp(int(p.get('bond_points',0)),0,20),1,40)
    legendary = bool(p.get('legendary',False) and p.get('legend_ac',False))
    def ac(v): return clamp(10+rnd((v-30)/14),10,18 if legendary else 17)
    def mod(s): return clamp(math.floor((s-10)/4),-2,8)
    hp = 15+rnd(stats[0]/8)+steps*(4+rnd(stats[0]/35))
    return dict(max_hp=hp, strength=attrs[1], constitution=attrs[2], intelligence=attrs[3], wisdom=attrs[4], dexterity=attrs[5], charisma=cha,
                attack_mod=mod(attrs[1]), special_mod=mod(attrs[3]), speed_mod=mod(attrs[5]), bond_mod=mod(cha), physical_ac=ac(stats[2]), special_ac=ac(stats[4]),
                to_hit=3+(level-1)//25)

def attack_dice(move, level):
    power=move.get('power')
    if move.get('category')=='status' or not power: return None
    return {'count':1+(level-1)//20, 'sides':4 if power<=30 else 6 if power<=55 else 8 if power<=80 else 10 if power<=105 else 12}

def basic_move(n):
    x=MOVE_DB.get(n, [40,100,'physical']); return {'name':n,'type':MOVE_TYPES.get(n,'normal'),'power':x[0], 'accuracy':x[1],'category':x[2], 'pp':15,
             'effect':'Offline fallback, DM may adjudicate unusual effects', 'target':'selected-pokemon', 'ailment':x[3] if len(x)>3 else 'none','ailment_chance':x[4] if len(x)>4 else 0}

def fallback_mon(name, level=5):
    src = BASE_POKE.get(name)
    if not src: return None
    # These are approximate fallback move levels, not a substitute for the online Pokédex.
    pool=[basic_move(m) | {'learned_at':i*5 if i>=3 else 1} for i,m in enumerate(src['moves'])]
    legal=[m for m in pool if m['learned_at']<=level]
    return {'dex_id':src['id'],'species':name,'name':name,'types':src['types'], 'stats':src['stats'],'abilities':src['abilities'], 'ability':src['abilities'][0],
            'level':level,'legendary':src.get('legendary',False),'legend_ac':False,'mega_forms':src.get('mega',[]),'allowed_moves':pool,'moves':choose_moves(legal), 'shiny':random.randrange(4096)==0,
            'tera_type':src['types'][0],'tera_enabled':False,'mega_enabled':False,'bond_points':0,'experience':0,'offline':True}

def choose_moves(pool):
    pool=list({m['name']:m for m in pool}.values())
    selected=random.sample(pool,min(4,len(pool))) if pool else []
    return [{**m,'remaining_pp':int(m.get('pp',15))} for m in selected]

def health_band(hp, max_hp):
    r=hp/max(1,max_hp)
    return 'Fainted' if hp<=0 else 'Healthy' if r>.75 else 'Injured' if r>.4 else 'Critical'

def defense_ac(target, category):
    calc=computed(target)
    base=calc['physical_ac' if category=='physical' else 'special_ac']
    key='defense' if category=='physical' else 'special-defense'
    stage=int(target.get('stages',{}).get(key,0))
    extra=int(target.get('temp_ac',{}).get('physical' if category=='physical' else 'special',0))
    return clamp(base+rnd(stage/2)+extra,5,22)

def type_effectiveness(attack_type, target, actor=None):
    types=target.get('types',[])
    if target.get('tera_active'): types=[target.get('tera_type','normal')]
    value=1
    for t in types: value*=TYPE_CHART.get(attack_type,{}).get(t,1)
    if attack_type=='ground' and target.get('ability')=='levitate' and (actor or {}).get('ability')!='mold-breaker': value=0
    if target.get('ability')=='wonder-guard' and value<=1 and (actor or {}).get('ability')!='mold-breaker':value=0
    return value

def hit_bonus(actor, move):
    accuracy=move.get('accuracy')
    delta=0 if accuracy is None else clamp(rnd((accuracy-100)/10),-6,0)
    return computed(actor)['to_hit']+delta+int(actor.get('stages',{}).get('accuracy',0))

def damage(actor, target, move, dice_sum, crit=False, weather='none', terrain='none'):
    """Same scaling, STAB, modifiers and rounding as v1.3. Critical dice sum is pre-doubled."""
    s=computed(actor); ts=computed(target)
    eff=type_effectiveness(move['type'], target, actor)
    base_types=actor.get('base_types', actor.get('types',[]))
    stab=1.5 if move['type'] in base_types else 1
    if actor.get('tera_active') and actor.get('tera_type')==move['type']:
        stab=2 if move['type'] in base_types else max(stab,1.5)
    if actor.get('ability')=='adaptability' and stab==1.5: stab=2
    category=move['category']
    mod=s['attack_mod' if category=='physical' else 'special_mod']+2*int(actor.get('stages',{}).get('attack' if category=='physical' else 'special-attack',0))
    if category=='physical' and actor.get('status')=='burn' and actor.get('ability')!='guts':mod=math.floor(mod/2)
    if actor.get('ability')=='guts' and actor.get('status') not in (None,'none') and category=='physical':mod+=3
    if actor.get('ability')=='huge-power' and category=='physical':mod+=4
    if actor.get('ability')=='technician' and (move.get('power') or 0)<=60:mod+=2
    amount=max(1,math.floor((dice_sum+mod)*stab*eff))
    if (move['type']=='fire' and weather=='sun') or (move['type']=='water' and weather=='rain'): amount=math.floor(amount*1.5)
    if (move['type']=='water' and weather=='sun') or (move['type']=='fire' and weather=='rain'): amount=math.floor(amount*.5)
    if (terrain=='electric' and move['type']=='electric') or (terrain=='grassy' and move['type']=='grass') or (terrain=='psychic' and move['type']=='psychic'):amount=math.floor(amount*1.2)
    if target.get('ability')=='thick-fat' and move['type'] in ('fire','ice'): amount=math.floor(amount*.5)
    if target.get('ability')=='multiscale' and target['current_hp']==ts['max_hp']: amount=math.floor(amount*.5)
    if target.get('ability') in ('filter','solid-rock') and eff>1:amount=math.floor(amount*.75)
    if eff==0 or target.get('protected'):amount=0
    if target.get('ability')=='sturdy' and target['current_hp']==ts['max_hp'] and amount>=target['current_hp'] and actor.get('ability')!='mold-breaker':amount=max(0,target['current_hp']-1)
    return min(max(0,amount),target['current_hp']),eff


def pokemon_view(p, full=True):
    if not full:return {'id':p['id'],'species':p['species'],'nickname':p.get('nickname') or p['species'],'dex_id':p.get('dex_id'), 'slot':p.get('slot'),'owner':p.get('owner')}
    x={k:v for k,v in p.items() if not k.startswith('_')}; x['calculated']=computed(p); return x
