"""Persistent read-only trip/charge recorder. No openpilot imports."""
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

MEB_INVALID_ENERGY_WH = {102250, 102300, 102350, 102375}

def stamp(t): return datetime.fromtimestamp(t,timezone.utc).isoformat(timespec='seconds')
def distance(a,b):
    p1,p2=math.radians(a['latitude']),math.radians(b['latitude'])
    h=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(b['longitude']-a['longitude'])/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,body TEXT); CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,path TEXT,body TEXT,created REAL);')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=20)
        try:
            with db:yield db
        finally:db.close()
    def load(self):
        with self.connect() as db: row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {}
    def save(self,state,events,now):
        with self.connect() as db:
            db.execute('INSERT INTO state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(json.dumps(state,allow_nan=False),))
            for path,payload in events:
                identity=payload.get('id') or payload['deviceId']+'|'+payload['updatedAt']
                db.execute('INSERT OR IGNORE INTO outbox VALUES (?,?,?,?)',(identity,path,json.dumps(payload,allow_nan=False),now))
    def first(self):
        with self.connect() as db:return db.execute('SELECT id,path,body FROM outbox ORDER BY created,rowid LIMIT 1').fetchone()
    def latest_telemetry(self):
        """Prioritize a snapshot without deleting any of the historical backlog."""
        with self.connect() as db:
            return db.execute("SELECT id,path,body FROM outbox WHERE path='/api/telemetry' ORDER BY created DESC,rowid DESC LIMIT 1").fetchone()
    def acknowledge(self,key):
        with self.connect() as db:db.execute('DELETE FROM outbox WHERE id=?',(key,))
    def count(self):
        with self.connect() as db:return db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]

class Engine:
    def __init__(self,store,device):
        self.store,self.device=store,device
        self.s=store.load()
        self.s.setdefault('vehicle',{})
        self.s.setdefault('field_measured_at',{})
        self.s.setdefault('charge_months',{})
        self.s.setdefault('charge_sessions',[])
        if self.s['vehicle'].get('battery_wh') in MEB_INVALID_ENERGY_WH:
            for key in ('battery_wh','soc_percent','charge_power_w','charging'):
                self.s['vehicle'].pop(key, None)
            self.s['field_measured_at'].pop('battery_wh', None)
            self.s.pop('energy_sample', None)
            self.s.pop('charge_candidate', None)
        self.s.pop('energy_sample', None)
        self.s.pop('charge_candidate', None)
        self.last_saved=0
        charge=self.s.get('charge')
        if charge and 'fast' not in charge:
            # Legacy active sessions have no contribution journal. Preserve
            # their totals; only retain fast evidence for future additions.
            duration=charge.get('duration_s',0)
            charge['fast']=bool(duration > 0 and charge.get('energy_kwh',0)*3600000/duration > 11000)
        candidate=self.s.get('charge_candidate')
        if candidate and any('end_wh' not in w for w in candidate.get('windows', [])):
            self.s.pop('charge_candidate', None)
        if self.s.get('trip'):
            self.s['trip']['partial']=True
            self.s['trip'].pop('last_motion', None)
            self.s['trip'].pop('last_clock', None)
            self.s['trip']['distance_complete'] = False
            self.s['trip']['energy_complete'] = False
    def tick(self,now,onroad,gps=None,sampled=None,enabled=None,motion=None,diagnostics=None,monotonic_now=None):
        if sampled and sampled.get('battery_wh') in MEB_INVALID_ENERGY_WH:
            sampled=dict(sampled)
            sampled.pop('battery_wh', None)
            sampled.pop('soc_percent', None)
        for key, value in (diagnostics or {}).items():
            self.s['vehicle'][key] = value
            self.s['field_measured_at'][key] = stamp(now)
        comma_onroad=onroad
        onroad=self._driving(onroad,motion)
        self.s['field_measured_at']['wheel_speed_mps']=stamp(now)
        self.s['vehicle'].update(comma_onroad=bool(comma_onroad),driving=onroad,
                                 gear=motion.get('gear') if motion else None,
                                 wheel_speed_mps=(motion.get('speed_mps') if motion and type(motion.get('speed_mps')) in (int,float) and math.isfinite(motion['speed_mps']) else None))
        if onroad is None:
            self.s.pop('energy_sample',None)
            self.s.pop('charge_candidate',None)
            if self.s.get('trip'):
                self.s['trip']['partial']=True
                self.s['trip']['last_at']=now
                self.s['trip'].pop('last_point',None)
                self.s['trip'].pop('last_motion',None)
                self.s['trip']['distance_complete']=False
                self.s['trip']['energy_complete']=False
        events=[];s=self.s;changed=onroad!=s.get('onroad');old_onroad=s.get('onroad')
        trip=s.get('trip')
        if onroad and not trip:
            trip=s['trip']={'id':str(uuid.uuid4()),'deviceId':self.device,'startedAt':stamp(now),'durationS':0,'distanceM':0,'route':[],'last_at':now,'partial':old_onroad is None,'distance_complete':True,'distance_source':'can_speed'}
        if trip:
            # Capture the actual CAN measurement, including the final driving
            # boundary, before telemetry throttling or the offroad transition.
            wh = (sampled or {}).get('battery_wh')
            soc = (sampled or {}).get('soc_percent')
            valid_wh = type(wh) in (int,float) and math.isfinite(wh) and 0 <= wh <= 150000
            valid_soc = type(soc) in (int,float) and math.isfinite(soc) and 0 <= soc <= 100
            if valid_wh or valid_soc:
                point = {'at':stamp(now), 'battery_wh':wh if valid_wh else None,
                         'soc_percent':soc if valid_soc else None}
                previous = trip.get('energy_end')
                if previous:
                    t = datetime.fromisoformat(previous['at']).timestamp()
                    old_wh = previous.get('battery_wh')
                    if (not valid_wh or old_wh is None or now-t > 120
                            or (wh != old_wh and (now <= t or abs(wh-old_wh)*3600/(now-t) > 250000))):
                        trip['energy_complete'] = False
                else:
                    # CAN sampling takes up to 4s, then sleeps 26s. Boundaries
                    # must allow one sampling cycle rather than one engine tick.
                    trip.setdefault('energy_complete', valid_wh and now-datetime.fromisoformat(trip['startedAt']).timestamp() <= 35)
                    trip['energy_start'] = point
                trip['energy_end'] = point
            elif sampled is not None and 'battery_wh' in sampled:
                trip['energy_complete'] = False
        if trip and onroad:
            clock = now if monotonic_now is None else monotonic_now
            dt = clock-trip.get('last_clock', clock)
            wall_dt = now-trip['last_at']
            trip['last_clock']=clock
            trip['last_at']=now
            if 0 <= dt <= 20:
                trip['durationS'] += dt
            else:
                trip['partial']=True
            speed = motion.get('speed_mps') if motion else None
            valid_speed = type(speed) in (int,float) and math.isfinite(speed) and 0 <= speed <= 70
            previous_speed = trip.get('last_motion')
            if valid_speed and previous_speed is not None and 0 < dt <= 3:
                trip['distanceM'] += (previous_speed+speed)*0.5*dt
            elif wall_dt > 0 and (previous_speed is None or dt > 3 or not valid_speed):
                trip['distance_complete']=False
            trip['last_motion'] = speed if valid_speed else None
            # Fresh, quantized odometer anchors validate/recover recorder outages.
            odo = (sampled or {}).get('odometer_km')
            if type(odo) in (int,float) and math.isfinite(odo) and odo >= 0:
                trip.setdefault('odometer_start', {'km':odo,'at':now})
                old_odo = trip.get('odometer_end')
                if old_odo and (odo < old_odo['km'] or (odo-old_odo['km'])*1000 > max(2000,(now-old_odo['at'])*70)):
                    trip['odometer_invalid']=True
                trip['odometer_end']={'km':odo,'at':now}
            if gps and now-trip.get('last_point_at',0)>=5:
                point=dict(gps,t=stamp(now));previous=trip.get('last_point')
                if previous:
                    d=distance(previous,point)
                    interval=max(1,now-trip.get('last_point_at',now))
                    if d>max(100,interval*70):point=None
                    # GPS is a map trace only. Tunnel gaps never gate CAN distance.
                if point:
                    trip['last_point'],trip['last_point_at']=point,now
                    if len(trip['route'])>=720:trip['route']=trip['route'][::2]
                    trip['route'].append(point)
        elif trip and onroad is False:
            end=trip.get('last_at',now)
            source = trip.get('distance_source', 'legacy_gps')
            a,b = trip.get('odometer_start'),trip.get('odometer_end')
            if not trip.get('distance_complete') and a and b and not trip.get('odometer_invalid'):
                odo_m = (b['km']-a['km'])*1000
                start = datetime.fromisoformat(trip['startedAt']).timestamp()
                if (a['at']-start <= 35 and end-b['at'] <= 35 and end > start
                        and odo_m >= 5000 and odo_m >= trip['distanceM']-2000
                        and odo_m <= (end-start)*70):
                    trip['distanceM']=odo_m
                    source='odometer_gap_recovery'
            payload={k:trip[k] for k in ('id','deviceId','startedAt','durationS','distanceM','route','partial')}
            payload['distanceSource']=source
            payload['distanceQuality']={'complete':bool(trip.get('distance_complete')),
                                        'estimated':source=='odometer_gap_recovery',
                                        'odometerStart':a,'odometerEnd':b}
            if not trip.get('distance_complete'):payload['partial']=True
            payload.update(endedAt=stamp(end),durationS=round(trip['durationS']),distanceM=round(trip['distanceM'],1))
            start_point, end_point = trip.get('energy_start'), trip.get('energy_end')
            complete = bool(trip.get('energy_complete') and start_point and end_point
                and abs(end-datetime.fromisoformat(end_point['at']).timestamp()) <= 35
                and datetime.fromisoformat(start_point['at']) < datetime.fromisoformat(end_point['at']))
            payload['tripMeasurements'] = {'start':start_point, 'end':end_point, 'complete':complete}

            if payload['distanceM']>=100:events.append(('/api/trips',payload))
            if trip.get('last_point'):s['parking']=dict(trip['last_point'],measured_at=stamp(end))
            s['trip']=None
        if gps:
            s['gps']=dict(gps,measured_at=stamp(now),fresh=True)
            if onroad is False:s['parking']=dict(gps,measured_at=stamp(now))
        s['onroad']=onroad
        if sampled is not None:
            for key,value in sampled.items():
                if (value is not None and (not isinstance(value,float) or math.isfinite(value))) or (value is None and key in ('bms_target_soc_percent', 'dcdc_temperature_c')):
                    s['vehicle'][key]=value;s['field_measured_at'][key]=stamp(now)
            if sampled:s['measured_at']=stamp(now)
        try:
            from .charging_mode import charging_mode
            from .charge_recorder import update as update_can_charge
        except (ImportError, ValueError):
            from openpilot.selfdrive.carrot.ha.charging_mode import charging_mode
            from openpilot.selfdrive.carrot.ha.charge_recorder import update as update_can_charge
        signal=charging_mode({**s['vehicle'], 'field_measured_at':s['field_measured_at']},now)
        previous_charging=s['vehicle'].get('charging')
        previous_mode=s['vehicle'].get('charge_mode')
        update_can_charge(s,now,signal,sampled.get('battery_wh') if sampled else None)
        s.pop('charge_candidate',None)
        s['vehicle'].update(charging=signal['charging'],charge_mode=signal['mode'],
                            charge_state_source='can_request')
        if signal['charging'] is not True:
            s['vehicle']['charge_power_w']=0 if signal['charging'] is False else None
            s.pop('can_power_sample',None)
        elif sampled and sampled.get('battery_wh') is not None:
            previous=s.get('can_power_sample')
            wh=sampled['battery_wh']
            if previous and 0<now-previous['at']<=90:
                power=(wh-previous['wh'])*3600/(now-previous['at'])
                s['vehicle']['charge_power_w']=round(power) if 0<=power<=250000 else None
            s['can_power_sample']={'wh':wh,'at':now}
        changed=changed or previous_charging!=signal['charging'] or previous_mode!=signal['mode']
        interval=30 if onroad else 60
        if changed or now-s.get('last_upload',0)>=interval:
            vehicle=dict(s['vehicle'])
            measured=s['field_measured_at'].get('battery_wh') or s.get('measured_at')
            age=now-datetime.fromisoformat(measured).timestamp() if measured else 999999
            vehicle.update(field_measured_at=s['field_measured_at'],measured_at=measured,stale=age>120,charge_months=s['charge_months'],charge_sessions=s['charge_sessions'],charge_active_session=s.get('charge'),parking=s.get('parking'))
            if vehicle.get('battery_wh') is not None:vehicle.update(capacity_wh=78000,soc_percent=min(100,vehicle['battery_wh']/780))
            events.append(('/api/telemetry',{'deviceId':self.device,'updatedAt':stamp(now),'onroad':int(onroad is True),'ignition':int(comma_onroad),'enabled':enabled,'gps':s.get('gps') or {},'vehicle':vehicle}))
            s['last_upload']=now
        if events or now-self.last_saved>=5:
            self.store.save(s,events,now);self.last_saved=now
        return events

    def _driving(self, comma_onroad, motion):
        # Only fresh, valid carState is passed by the collector. IsOnroad is
        # comma mode, not movement. Never use stationary GPS to infer parking.
        if motion:
            speed=motion.get('speed_mps')
            gear=motion.get('gear')
            if type(speed) in (int,float) and math.isfinite(speed) and speed>=0:
                if speed>0.1:return True
                if gear=='park':return False
                if gear in ('drive','reverse','sport','low','eco','manumatic'):return True
                if gear=='neutral' and self.s.get('trip'):return True
            return None
        return None if comma_onroad else False
