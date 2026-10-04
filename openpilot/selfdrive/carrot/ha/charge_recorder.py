"""CAN-mode-led sessions. Energy estimates never create a charging session."""
import math
import uuid
from datetime import datetime, timezone, timedelta

MAX_GAP = 1800
INVALID_WH = {102250, 102300, 102350, 102375}

def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec='seconds')

def valid_energy(wh):
    return type(wh) in (int,float) and math.isfinite(wh) and 0<wh<=102325 and wh not in INVALID_WH

def finish(state, partial=False):
    charge=state.pop('charge',None)
    if charge:
        charge['partial']=bool(charge.get('partial') or partial)
        state['charge_sessions'].append(charge)
        state['charge_sessions']=state['charge_sessions'][-50:]
    state.pop('can_charge_gap',None)

def add_energy(state, charge, wh, at, corrected=False):
    if not valid_energy(wh):return
    peak=charge.get('peak_wh')
    if peak is None:
        charge['peak_wh']=wh;charge['last_energy_at']=at;return
    added=max(0,wh-peak)
    if added<50:return  # Accumulate quantized steps, never count a rebound twice.
    dt=at-charge.get('last_energy_at',at)
    if dt<=0 or added*3600/dt>250000:
        charge['partial']=True;return
    kwh=added/1000
    charge['peak_wh']=wh;charge['last_energy_at']=at;charge['energy_kwh']+=kwh
    if corrected:charge['corrected_energy_kwh']+=kwh
    code=charge['can_mode'];kind='fast' if code==6 else 'slow'
    month=datetime.fromtimestamp(at,timezone(timedelta(hours=9))).strftime('%Y-%m')
    ledger=state['charge_months'].setdefault(month,{'slow_kwh':0,'fast_kwh':0,'cost_krw':0})
    ledger[kind+'_kwh']+=kwh;ledger['cost_krw']+=kwh*(320 if code==6 else 280)
    charge['month_energy'][month]=charge['month_energy'].get(month,0)+kwh

def update(state, now, signal, wh=None):
    valid=valid_energy(wh)
    charge=state.get('charge');active=signal['charging']
    if charge and charge.get('source')!='can_request':
        finish(state,True);charge=None
    if active is None:
        if charge:
            state.setdefault('can_charge_gap',charge.get('last_mode_at',now))
            if now-state['can_charge_gap']>MAX_GAP:finish(state,True)
        return
    mode_at=datetime.fromisoformat(signal['measured_at']).timestamp() if signal.get('measured_at') else now
    if active is False:
        # Capture the final nearby stationary energy sample, not a new charge.
        if charge and 'can_charge_gap' not in state and not signal.get('driving') and 0<=mode_at-charge['last_mode_at']<=45:
            add_energy(state,charge,wh,mode_at)
        finish(state,partial='can_charge_gap' in state)
        if valid:state['can_energy_anchor']={'wh':wh,'at':now}
        return
    code=signal['code'];gap=state.get('can_charge_gap')
    if charge and charge['can_mode']!=code:
        finish(state,True);charge=None;gap=None
    if charge and gap is not None:
        elapsed=mode_at-charge['last_mode_at']
        delta=wh-charge.get('peak_wh',wh) if valid and charge.get('peak_wh') is not None else None
        if elapsed>MAX_GAP or elapsed<=0 or delta is None or delta<0 or delta*3600/elapsed>250000:
            finish(state,True);charge=None;gap=None
        else:
            charge.setdefault('signal_gaps', []).append({'started_at':stamp(charge['last_mode_at']), 'ended_at':stamp(mode_at)})
            charge['unknown_duration_s']+=elapsed
            charge['gap_corrected']=True;charge['gap_count']+=1
            state.pop('can_charge_gap',None)
    if charge is None:
        anchor=state.get('can_energy_anchor')
        use_anchor=valid and anchor and 0<=now-anchor['at']<=45 and anchor['wh']<=wh
        baseline=anchor['wh'] if use_anchor else wh if valid else None
        energy_at=anchor['at'] if use_anchor else mode_at
        charge=state['charge']={'id':str(uuid.uuid4()),'source':'can_request','can_mode':code,
            'started_at':stamp(mode_at),'ended_at':stamp(mode_at),'energy_kwh':0,'duration_s':0,
            'confirmed_duration_s':0,'unknown_duration_s':0,'gap_corrected':False,'gap_count':0,
            'corrected_energy_kwh':0,'signal_gaps':[],'partial':baseline is None,'fast':code==6,'peak_wh':baseline,
            'month_energy':{},'last_mode_at':mode_at,'last_energy_at':energy_at}
    previous=charge['last_mode_at']
    if gap is None and mode_at>previous:charge['confirmed_duration_s']+=mode_at-previous
    charge['duration_s']=charge['confirmed_duration_s']
    charge['last_mode_at']=max(mode_at,previous);charge['ended_at']=stamp(charge['last_mode_at'])
    add_energy(state,charge,wh,mode_at,corrected=gap is not None)
