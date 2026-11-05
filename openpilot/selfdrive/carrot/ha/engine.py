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


# --- openpilot assist statistics (carrot-ha docs/OPENPILOT_ASSIST_STATS_PLAN_2026-11-05.md) ---
# Each 1s CAN-speed distance increment is attributed to the control class of
# the previous fresh sample. Unknown signals are never guessed; gaps end
# streaks; engagement counts are 1s-sample based and ignore re-observation.
ASSIST_VERSION = 1
ASSIST_CLASSES = ('manual', 'latOnly', 'longOnly', 'both')
ASSIST_ACTIVE = ('latOnly', 'longOnly', 'both')
ASSIST_BUCKET_S = 900
ASSIST_STREAK_MIN_M = 100
ASSIST_STREAK_KEEP = 50

def assist_class(control):
    if not control:
        return None
    lat, lon = control.get('lat'), control.get('long')
    if type(lat) is not bool or type(lon) is not bool:
        return None
    return ('both' if lon else 'latOnly') if lat else ('longOnly' if lon else 'manual')

def assist_enabled(control):
    value = (control or {}).get('enabled')
    return value if type(value) is bool else None

def assist_new():
    return {'m': {k: 0.0 for k in ASSIST_CLASSES + ('unknown',)},
            'enabled': {'on': 0.0, 'off': 0.0, 'unknown': 0.0},
            'known_s': 0.0, 'assist_s': 0.0, 'engagements': 0, 'disengagements': 0,
            'buckets': {}, 'streaks': [], 'streak_count': 0,
            'longest_m': 0.0, 'longest_s': 0.0, 'cur': None}

def assist_close(a, end, broken):
    cur = a.get('cur')
    a['cur'] = None
    if not cur or cur['m'] <= 0:
        return
    if cur['m'] > a['longest_m']:
        a['longest_m'], a['longest_s'] = cur['m'], cur['s']
    if cur['m'] >= ASSIST_STREAK_MIN_M:
        a['streak_count'] += 1
        a['streaks'].append({'startAt': stamp(cur['start']), 'endAt': stamp(end),
                             'distanceM': round(cur['m'], 1), 'brokenByGap': bool(broken)})
        a['streaks'].sort(key=lambda x: -x['distanceM'])
        del a['streaks'][ASSIST_STREAK_KEEP:]

def assist_gap(trip, now):
    """Distance or signal continuity was lost: end any streak without bridging."""
    a = trip.get('assist')
    if a:
        assist_close(a, trip.get('assist_last_at', now), True)
    trip.pop('assist_prev', None)
    trip.pop('assist_prev_enabled', None)

def assist_buckets(a, key, start, end, inc):
    """Split one increment across UTC 15-minute buckets by elapsed time."""
    span = end - start
    t = start
    while True:
        edge = (math.floor(t / ASSIST_BUCKET_S) + 1) * ASSIST_BUCKET_S
        part_end = min(edge, end)
        share = inc if span <= 0 else inc * (part_end - t) / span
        bucket = a['buckets'].setdefault(str(int(edge - ASSIST_BUCKET_S)), {k: 0.0 for k in ASSIST_CLASSES + ('unknown',)})
        bucket[key] += share
        if part_end >= end:
            return
        t = part_end

def assist_integrate(trip, now, dt, inc):
    a = trip.setdefault('assist', assist_new())
    prev = trip.get('assist_prev')
    key = prev if prev in ASSIST_CLASSES else 'unknown'
    a['m'][key] += inc
    assist_buckets(a, key, now - dt, now, inc)
    en = trip.get('assist_prev_enabled')
    a['enabled']['on' if en is True else 'off' if en is False else 'unknown'] += inc
    if key != 'unknown':
        a['known_s'] += dt
    if key in ASSIST_ACTIVE:
        a['assist_s'] += dt
        if not a['cur']:
            a['cur'] = {'start': now - dt, 'm': 0.0, 's': 0.0}
        a['cur']['m'] += inc
        a['cur']['s'] += dt
    else:
        assist_close(a, now - dt, key == 'unknown')
    trip['assist_last_at'] = now

def assist_observe(trip, control):
    """Count transitions only between two consecutive fresh samples."""
    a = trip.setdefault('assist', assist_new())
    cls = assist_class(control)
    prev = trip.get('assist_prev')
    if prev in ASSIST_CLASSES and cls in ASSIST_CLASSES:
        if prev == 'manual' and cls in ASSIST_ACTIVE:
            a['engagements'] += 1
        elif prev in ASSIST_ACTIVE and cls == 'manual':
            a['disengagements'] += 1
    trip['assist_prev'] = cls
    trip['assist_prev_enabled'] = assist_enabled(control)

def assist_payload(trip, end):
    a = trip.get('assist')
    if not a:
        return None
    assist_close(a, end, False)
    r = lambda v: round(v, 1)
    m = a['m']
    buckets = [{'at': stamp(int(at)), **{k + 'M': r(v[k]) for k in ASSIST_CLASSES + ('unknown',)}}
               for at, v in sorted(a['buckets'].items(), key=lambda x: int(x[0]))]
    return {'version': ASSIST_VERSION, 'basisDistanceM': r(sum(m.values())),
            **{k + 'M': r(m[k]) for k in ASSIST_CLASSES + ('unknown',)},
            'knownDurationS': round(a['known_s']), 'assistDurationS': round(a['assist_s']),
            'enabled': {'onM': r(a['enabled']['on']), 'offM': r(a['enabled']['off']),
                        'unknownM': r(a['enabled']['unknown'])},
            'engagements': a['engagements'], 'disengagements': a['disengagements'],
            'longestStreakM': r(a['longest_m']), 'longestStreakS': round(a['longest_s']),
            'streakCount': a['streak_count'], 'streaks': a['streaks'], 'buckets': buckets}

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,body TEXT); CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,path TEXT,body TEXT,created REAL); CREATE INDEX IF NOT EXISTS outbox_lane_created ON outbox(path,created);')
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
    def first_for(self, path):
        """Independent FIFO lanes preserve every failed record without cross-blocking."""
        with self.connect() as db:
            return db.execute('SELECT id,path,body FROM outbox WHERE path=? ORDER BY created,rowid LIMIT 1',(path,)).fetchone()
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
            assist_gap(self.s['trip'], self.s['trip'].get('last_at', 0))
    def tick(self,now,onroad,gps=None,sampled=None,enabled=None,motion=None,diagnostics=None,monotonic_now=None,control=None):
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
                assist_gap(self.s['trip'], now)
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
                # Cluster-SOC candidate (0x14A) is comparison-only: it never
                # gates energy completeness or replaces the Wh-based SOC.
                display = (sampled or {}).get('display_soc_candidate_percent')
                display_at = ((sampled or {}).get('_battery_can_measured_at') or {}).get('display_soc_candidate_percent')
                if (type(display) in (int,float) and math.isfinite(display) and 0 <= display <= 100
                        and type(display_at) in (int,float) and math.isfinite(display_at) and 0 <= now-display_at <= 180):
                    point.update(display_soc_candidate_percent=display, display_soc_candidate_measured_at=stamp(display_at))
                else:
                    point.update(display_soc_candidate_percent=None, display_soc_candidate_measured_at=None)
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
                increment = (previous_speed+speed)*0.5*dt
                trip['distanceM'] += increment
                assist_integrate(trip, now, dt, increment)
            elif wall_dt > 0 and (previous_speed is None or dt > 3 or not valid_speed):
                trip['distance_complete']=False
                assist_gap(trip, now)
            assist_observe(trip, control)
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
            assist = assist_payload(trip, end)
            if assist:
                payload['assist'] = assist

            if payload['distanceM']>=100:events.append(('/api/trips',payload))
            if trip.get('last_point'):s['parking']=dict(trip['last_point'],measured_at=stamp(end))
            s['trip']=None
        if gps:
            s['gps']=dict(gps,measured_at=stamp(now),fresh=True)
            if onroad is False:s['parking']=dict(gps,measured_at=stamp(now))
        s['onroad']=onroad
        if sampled is not None:
            try:
                from .telemetry_fields import BATTERY_MONITOR_KEYS
            except (ImportError, ValueError):
                from openpilot.selfdrive.carrot.ha.telemetry_fields import BATTERY_MONITOR_KEYS
            received = sampled.get('_battery_can_measured_at') or {}
            for key,value in sampled.items():
                if key == '_battery_can_measured_at':
                    continue
                if key in BATTERY_MONITOR_KEYS:
                    measured = received.get(key)
                    if type(measured) not in (int, float) or not math.isfinite(measured) or not 0 <= now-measured <= 180:
                        continue
                    previous = s['field_measured_at'].get(key)
                    if previous and datetime.fromisoformat(previous).timestamp() > measured:
                        continue
                    if value is None or not isinstance(value, float) or math.isfinite(value):
                        s['vehicle'][key] = value
                        s['field_measured_at'][key] = stamp(measured)
                    continue
                if (value is not None and (not isinstance(value,float) or math.isfinite(value))) or (value is None and key in ('bms_target_soc_percent', 'dcdc_temperature_c')):
                    s['vehicle'][key]=value;s['field_measured_at'][key]=stamp(now)
            if sampled:s['measured_at']=stamp(now)
        try:
            from .charging_mode import charging_mode, actual_power_voltage
            from .charge_recorder import update as update_can_charge
        except (ImportError, ValueError):
            from openpilot.selfdrive.carrot.ha.charging_mode import charging_mode, actual_power_voltage
            from openpilot.selfdrive.carrot.ha.charge_recorder import update as update_can_charge
        signal=charging_mode({**s['vehicle'], 'field_measured_at':s['field_measured_at']},now)
        previous_charging=s['vehicle'].get('charging')
        previous_mode=s['vehicle'].get('charge_mode')
        update_can_charge(s,now,signal,sampled.get('battery_wh') if sampled else None)
        s.pop('charge_candidate',None)
        s['vehicle'].update(charging=signal['charging'],charge_mode=signal['mode'],
                            charge_state_source='can_actual' if signal['source_kind']=='actual' else 'can_request')
        power, voltage, measured = actual_power_voltage(s['vehicle'] | {'field_measured_at':s['field_measured_at']}, signal)
        s['vehicle'].update(charge_power_w=power, hv_voltage=voltage)
        s.pop('can_power_sample', None)
        if measured:
            s['field_measured_at'].update(charge_power_w=measured, hv_voltage=measured)
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
